"""
快捷工具层 — LLM 首选的 4 个工具
原有工具保留不动，这里是简化入口。
"""
import json
import os

from MCP_Tools.mcp_init import mcp
from MCP_Tools.post_integral import _fill_struct, _validate_scalars
from PostDrive.PostDrive import PostDrive
from PostDrive.ForceMomentIntegralStruct import ForceMoment, ForceMomentRes
from PostDrive.PostIntegral import PostIntegral
from PostDrive.VelocityGradientStruct import VelocityGradientStruct
from PostDrive.PostVelocityGradient import PostVelocityGradient
from MCP_Tools.tool import getPostInfo
import vtk

# ============================================================
#  会话状态（缓存）
# ============================================================
_cached_file_path: str = ''
_cached_postDrive: PostDrive = None


def _resolve_path(file_path: str) -> str:
    """路径规范化：正斜杠替换 + normpath"""
    return os.path.normpath(file_path.replace('\\', '/'))


def _ensure_loaded(file_path: str = '') -> tuple:
    """确保文件已加载，返回 (postDrive, error_dict)。
    - file_path 非空且与缓存不同 → 重新加载
    - file_path 非空且与缓存相同 → 复用
    - file_path 为空 → 用缓存，缓存为空则报错
    """
    global _cached_file_path, _cached_postDrive

    if file_path:
        c_path = _resolve_path(file_path)
        if not os.path.isabs(c_path):
            # 如果有缓存文件，用缓存文件的目录拼接；否则报错
            if _cached_file_path:
                base_dir = os.path.dirname(_cached_file_path)
                c_path = os.path.join(base_dir, c_path)
            else:
                return None, {"error": f"Relative path '{file_path}' but no file loaded yet. Please use absolute path."}

        if c_path == _cached_file_path and _cached_postDrive is not None:
            return _cached_postDrive, None

        if not os.path.exists(c_path):
            return None, {"error": f"File not found: {c_path}"}

        try:
            pd = PostDrive()
            pd.readerPostFile([c_path])
            _cached_file_path = c_path
            _cached_postDrive = pd
            return pd, None
        except Exception as e:
            return None, {"error": f"Failed to load file: {str(e)}"}
    else:
        if _cached_postDrive is not None:
            return _cached_postDrive, None
        return None, {"error": "No file loaded. Please provide file_path."}


def _get_output_dir() -> str:
    """输出目录 = 当前加载文件的所在目录"""
    if _cached_file_path:
        return os.path.dirname(_cached_file_path)
    return ''


# ============================================================
#  Tool 1: loadFile
# ============================================================
@mcp.tool()
def loadFile(file_path: str) -> dict:
    """Load a post-processing file and return summary info (zones, scalars, bounds).
    Use forward slashes in path: D:/data/ysy.cgns
    Once loaded, other tools can work on this file without specifying the path again.
    """
    pd, err = _ensure_loaded(file_path)
    if err:
        return err
    try:
        data = getPostInfo(pd.getOutPut())
        data["file"] = _cached_file_path
        data["time_steps"] = pd.getTimeCount()
        return data
    except Exception as e:
        return {"error": str(e)}


# ============================================================
#  Tool 2: calculate
# ============================================================

# --- 算法注册表 ---
_METHODS = {}


def _register_method(name, description, param_class, execute_fn):
    _METHODS[name] = {
        "description": description,
        "param_class": param_class,
        "execute": execute_fn,
    }


def _run_force_moment(pd, struct, zone_name):
    """执行力/力矩积分"""
    err = _validate_scalars(pd, struct)
    if err:
        return err
    if zone_name and not pd.checkZoneNameInData(zone_name):
        zone_name = ''
    integral = PostIntegral()
    result: ForceMomentRes = integral.forceMomentIntegtal(
        pd.getOutPut(), struct, zone_name
    )
    res = result.__dict__
    # 结构化输出
    output = {
        "force": {
            "x": res["force_x"],
            "y": res["force_y"],
            "z": res["force_z"],
        },
        "moment": {
            "x": res["moment_x"],
            "y": res["moment_y"],
            "z": res["moment_z"],
        },
    }
    # 如果参考条件有意义（非默认值），输出气动系数
    has_ref = (struct.density is not None and struct.velocity is not None
               and struct.refArea is not None and struct.refLength is not None)
    if has_ref:
        output["coefficients"] = {
            "lift": res["lift_coefficient"],
            "drag": res["drag_coefficient"],
            "side_force": res["side_force_coefficient"],
            "pitch_moment": res["pitch_moment_coefficient"],
            "yaw_moment": res["yaw_moment_coefficient"],
            "roll_moment": res["roll_moment_coefficient"],
        }
    else:
        output["note"] = "Reference conditions not fully set, coefficients not calculated."
    return output


def _run_velocity_gradient(pd, struct, zone_name):
    """执行速度梯度计算"""
    multi_block = pd.getOutPut()
    gradient = PostVelocityGradient()
    gradient.CulVelocityGradient(multi_block, struct)
    # 保存到文件所在目录
    out_dir = os.path.join(_get_output_dir(), "VelocityGradient")
    if os.path.exists(out_dir):
        import shutil
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    out_path = os.path.join(out_dir, "res.vtm")
    writer = vtk.vtkXMLMultiBlockDataWriter()
    writer.SetInputData(multi_block)
    writer.SetFileName(out_path)
    writer.Write()
    return {"result": "OK", "output_file": out_path}


# 注册算法
_register_method(
    "force_moment",
    "Calculate force and moment integral (CL, CD, etc.)",
    ForceMoment,
    _run_force_moment,
)
_register_method(
    "velocity_gradient",
    "Calculate velocity gradient, vorticity, Cp, Mach, sound speed",
    VelocityGradientStruct,
    _run_velocity_gradient,
)


@mcp.tool()
def calculate(method: str, file_path: str = '', zoneName: str = '', params: str = '{}') -> dict:
    """Unified calculation tool. Runs an algorithm on the loaded file.
    Args:
        method: Algorithm name. Available: "force_moment", "velocity_gradient"
        file_path: Optional. File to analyze. If omitted, uses the previously loaded file.
        zoneName: Optional. Zone name to calculate on. Empty = all zones merged.
        params: Optional JSON string of algorithm-specific parameters. Use getMethodTemplate to see available params.
    """
    if method not in _METHODS:
        return {"error": f"Unknown method '{method}'. Available: {list(_METHODS.keys())}"}

    pd, err = _ensure_loaded(file_path)
    if err:
        return err

    entry = _METHODS[method]
    struct = entry["param_class"]()
    # 填充用户参数
    try:
        user_params = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as e:
        return {"error": f"Invalid params JSON: {str(e)}"}
    _fill_struct(struct, user_params)

    try:
        return entry["execute"](pd, struct, zoneName)
    except Exception as e:
        return {"error": str(e)}


# ============================================================
#  Tool 3: listFiles
# ============================================================
@mcp.tool()
def listFiles(directory: str = '', suffix: str = '') -> dict:
    """List files in a directory. Defaults to the loaded file's directory.
    Args:
        directory: Optional. Directory to list. If omitted, uses the loaded file's directory.
        suffix: Optional. Filter by extension, e.g. '.cgns', '.plt'
    """
    target_dir = directory
    if not target_dir:
        target_dir = _get_output_dir()
    if not target_dir:
        return {"error": "No directory specified and no file loaded."}

    target_dir = _resolve_path(target_dir)
    if not os.path.isdir(target_dir):
        return {"error": f"Directory not found: {target_dir}"}

    files = []
    for f in os.listdir(target_dir):
        if os.path.isfile(os.path.join(target_dir, f)):
            if not suffix or f.lower().endswith(suffix.lower()):
                files.append(f)
    return {"directory": target_dir, "files": files, "count": len(files)}


# ============================================================
#  Tool 4: getMethodTemplate
# ============================================================
@mcp.tool()
def getMethodTemplate(method: str = '') -> dict:
    """Get available calculation methods and their parameter templates.
    Args:
        method: Method name. If empty, returns list of all available methods.
    """
    if not method:
        methods = {}
        for name, entry in _METHODS.items():
            methods[name] = entry["description"]
        return {"available_methods": methods}

    if method not in _METHODS:
        return {"error": f"Unknown method '{method}'. Available: {list(_METHODS.keys())}"}

    entry = _METHODS[method]
    struct = entry["param_class"]()
    template = struct.__dict__.copy()
    return {
        "method": method,
        "description": entry["description"],
        "parameters": template,
    }
