import json
import os
import typing
import pandas as pd

from MCP_Tools.mcp_init import mcp
from MCP_Tools.post_file_data_tools import *
from PostDrive.ForceMomentIntegralStruct import *
from PostDrive.PostIntegral import *
import vtk


def _fill_struct(struct, params: dict):
    """通用参数填充：从 dict 赋值到 struct 的同名属性，自动类型转换"""
    for key, value in params.items():
        if not hasattr(struct, key):
            continue
        current = getattr(struct, key)
        if isinstance(current, float) and not isinstance(value, float):
            value = float(value)
        setattr(struct, key, value)


def _validate_scalars(postDrive, forceMoment: ForceMoment) -> typing.Optional[dict]:
    """校验标量名是否存在于数据中，失败返回 error dict，成功返回 None"""
    for field in ('shear_force_x', 'shear_force_y', 'shear_force_z'):
        val = getattr(forceMoment, field, '')
        if val and not postDrive.checkScalarNameInData(val):
            return {"error": f"{field} scalar '{val}' not found in data"}
    if forceMoment.pressure and not postDrive.checkScalarNameInData(forceMoment.pressure):
        return {"error": f"pressure scalar '{forceMoment.pressure}' not found in data"}
    return None


def calculateForceMomentIntegtal_tool(jsonParams: str) -> dict:
    c_global_postDrive = get_global_postDrive()
    if c_global_postDrive is None:
        return {"error": "No file loaded. Please call getPostFileDataInfo first."}
    res = json.loads(jsonParams)
    forceMoment = ForceMoment()
    _fill_struct(forceMoment, res)
    multiBlockDataSet = c_global_postDrive.getOutPut()
    # 校验标量名
    err = _validate_scalars(c_global_postDrive, forceMoment)
    if err:
        return err
    # 校验区域名
    zoneName = res.get("zoneName", "")
    if zoneName and not c_global_postDrive.checkZoneNameInData(zoneName):
        zoneName = ""
    postIntegral = PostIntegral()
    forceMomentRes: ForceMomentRes = postIntegral.forceMomentIntegtal(
        multiBlockDataSet, forceMoment, zoneName
    )
    return forceMomentRes.__dict__


# @mcp.tool()
def getForceMomentIntegtalParameTemplate() -> dict:
    """Get parameter template for force and moment integral calculation."""
    forceMoment = ForceMoment()
    res = forceMoment.__dict__.copy()
    res["zoneName"] = ""
    return res


# @mcp.tool()
def calculateForceMomentIntegtal(jsonParams: str) -> dict:
    """Calculate force and moment integral. Pass parameters as JSON string.
    Keys must match the template exactly (case-sensitive, no extra keys).
    """
    return calculateForceMomentIntegtal_tool(jsonParams)


# @mcp.tool()
def calculateForceMomentIntegtalByFile(file_path: str) -> dict:
    """Calculate force and moment integral from a JSON or Excel file."""
    if not os.path.exists(file_path):
        return {"error": f"file {file_path} not found"}

    ext = os.path.splitext(file_path)[1].lower()
    jsonParams = ""

    if ext == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            jsonParams = f.read()
    elif ext in [".xlsx", ".xls"]:
        try:
            df = pd.read_excel(file_path, header=None)
            data_dict = {}
            for index, row in df.iterrows():
                if index == 0:
                    continue
                if len(row) >= 2:
                    key = str(row[0])
                    val = row[1]
                    if pd.isna(val):
                        val = None
                    data_dict[key] = val
            jsonParams = json.dumps(data_dict, ensure_ascii=False)
        except Exception as e:
            return {"error": f"reading excel file: {str(e)}"}
    else:
        return {"error": f"unsupported file format: {ext}"}
    return calculateForceMomentIntegtal_tool(jsonParams)
