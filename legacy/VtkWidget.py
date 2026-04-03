import numpy as np
from PyQt5.QtGui import QColor, QVector3D
from vtkmodules.qt.QVTKRenderWindowInteractor import *
from vtkmodules.all import *
from enum import Enum


class ViewDirectType(Enum):
    View_DefaultView = 0
    View_FrontView = 1
    View_BackView = 2
    View_LeftView = 3
    View_RightView = 4
    View_PlanView = 5
    View_UpwardnView = 6
    View_RefreshView = 7
    View_ResetView = 8   # 只重置大小，不重置角度
    View_RecoverView = 9   # 完全重置
    View_RememberView = 10


class VtkWidget(QVTKRenderWindowInteractor):
    def __init__(self, parent=None):
        super(VtkWidget, self).__init__(parent)
        vtkOutputWindow.SetGlobalWarningDisplay(0)

        # --- 渲染器 ---
        self._renderer = vtkRenderer()
        self._renderer.SetBackground(0.05, 0.10, 0.25)   # 底部深蓝
        self._renderer.SetBackground2(0.20, 0.35, 0.60)  # 顶部亮蓝
        self._renderer.GradientBackgroundOn()
        self.GetRenderWindow().AddRenderer(self._renderer)

        # --- 交互器样式 ---
        style = vtkInteractorStyleTrackballCamera()
        self.SetInteractorStyle(style)

        # --- 内部 Actor 列表 ---
        self._actors: list[vtkActor] = []

        # --- 坐标轴小部件 ---
        self._axes_actor = vtkAxesActor()
        self._orientation_widget = vtkOrientationMarkerWidget()
        self._orientation_widget.SetOrientationMarker(self._axes_actor)
        self._orientation_widget.SetInteractor(self)
        self._orientation_widget.SetViewport(0.0, 0.0, 0.2, 0.2)
        self._orientation_widget.SetEnabled(1)
        self._orientation_widget.InteractiveOff()

        # --- 色卡（LookupTable + ScalarBar）---
        self._lut = vtkLookupTable()
        self._lut.SetNumberOfTableValues(256)
        self._lut.SetHueRange(0.667, 0.0)   # 蓝→红
        self._lut.SetSaturationRange(1.0, 1.0)
        self._lut.SetValueRange(1.0, 1.0)
        self._lut.SetRange(0.0, 1.0)
        self._lut.Build()

        self._scalar_bar = vtkScalarBarActor()
        self._scalar_bar.SetLookupTable(self._lut)
        self._scalar_bar.SetNumberOfLabels(5)
        self._scalar_bar.SetWidth(0.08)
        self._scalar_bar.SetHeight(0.4)
        self._scalar_bar.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        self._scalar_bar.GetPositionCoordinate().SetValue(0.91, 0.3)
        self._renderer.AddActor2D(self._scalar_bar)

        # --- 灯光 ---
        self._setup_lights()

        # 监听相机变化以同步手电筒
        self._renderer.GetActiveCamera().AddObserver(
            vtkCommand.ModifiedEvent, self._on_camera_modified
        )

        self.Initialize()

    # ------------------------------------------------------------------ #
    #  灯光设置
    # ------------------------------------------------------------------ #
    def _setup_lights(self):
        self._renderer.AutomaticLightCreationOff()
        self._renderer.RemoveAllLights()

        cam = self._renderer.GetActiveCamera()
        pos = cam.GetPosition()
        fp = cam.GetFocalPoint()

        # 手电筒：位置跟随相机，方向指向焦点
        self._flashlight = vtkLight()
        self._flashlight.SetLightTypeToCameraLight()
        self._flashlight.SetPosition(pos)
        self._flashlight.SetFocalPoint(fp)
        self._flashlight.SetIntensity(0.8)
        self._flashlight.SetColor(1.0, 1.0, 1.0)
        self._renderer.AddLight(self._flashlight)

        # 方向光（太阳）：斜上方 45° 照射
        self._sun_light = vtkLight()
        self._sun_light.SetLightTypeToSceneLight()
        self._sun_light.SetPosition(1.0, 1.0, 1.0)   # 斜上方
        self._sun_light.SetFocalPoint(0.0, 0.0, 0.0)
        self._sun_light.SetIntensity(0.6)
        self._sun_light.SetColor(1.0, 0.95, 0.8)      # 暖白色
        self._sun_light.PositionalOff()
        self._renderer.AddLight(self._sun_light)

    def _on_camera_modified(self, *_):
        """手电筒跟随相机同步更新。"""
        cam = self._renderer.GetActiveCamera()
        self._flashlight.SetPosition(cam.GetPosition())
        self._flashlight.SetFocalPoint(cam.GetFocalPoint())

    # ------------------------------------------------------------------ #
    #  Actor 管理
    # ------------------------------------------------------------------ #
    def add_actor(self, actor: vtkActor):
        """添加 Actor 并记录到内部列表。"""
        self._renderer.AddActor(actor)
        if actor not in self._actors:
            self._actors.append(actor)

    def remove_actor(self, actor: vtkActor):
        """移除指定 Actor。"""
        self._renderer.RemoveActor(actor)
        if actor in self._actors:
            self._actors.remove(actor)

    def clear_actors(self):
        """移除所有内部 Actor。"""
        for actor in list(self._actors):
            self._renderer.RemoveActor(actor)
        self._actors.clear()

    # ------------------------------------------------------------------ #
    #  LookupTable 范围
    # ------------------------------------------------------------------ #
    def set_lut_range(self, vmin: float, vmax: float):
        """设置色卡映射范围并刷新。"""
        self._lut.SetRange(vmin, vmax)
        self._lut.Build()
        self.refresh()

    def get_lut(self) -> vtkLookupTable:
        return self._lut

    def set_scalar_bar_title(self, title: str):
        self._scalar_bar.SetTitle(title)
        self.refresh()

    def set_scalar_bar_visible(self, visible: bool):
        self._scalar_bar.SetVisibility(1 if visible else 0)
        self.refresh()

    # ------------------------------------------------------------------ #
    #  相机视图
    # ------------------------------------------------------------------ #
    def set_view(self, view: ViewDirectType):
        dispatch = {
            ViewDirectType.View_FrontView: self.view_front,
            ViewDirectType.View_BackView: self.view_back,
            ViewDirectType.View_LeftView: self.view_left,
            ViewDirectType.View_RightView: self.view_right,
            ViewDirectType.View_PlanView: self.view_top,
            ViewDirectType.View_UpwardnView: self.view_bottom,
            ViewDirectType.View_RefreshView: self.refresh,
            ViewDirectType.View_ResetView: self.reset_zoom,
            ViewDirectType.View_RecoverView: self.reset_camera,
            ViewDirectType.View_DefaultView: self.reset_camera,
        }
        fn = dispatch.get(view)
        if fn:
            fn()

    def _apply_view_direction(self, position, view_up):
        """通用：设置相机方向并重置缩放。"""
        cam = self._renderer.GetActiveCamera()
        fp = cam.GetFocalPoint()
        dist = cam.GetDistance()
        cam.SetPosition(
            fp[0] + position[0] * dist,
            fp[1] + position[1] * dist,
            fp[2] + position[2] * dist,
        )
        cam.SetViewUp(*view_up)
        cam.OrthogonalizeViewUp()
        self._renderer.ResetCameraClippingRange()
        self.refresh()

    def view_front(self):
        """正视图：+Y 方向看向 -Y（朝 -Z 朝上）。"""
        self._apply_view_direction((0, 1, 0), (0, 0, 1))

    def view_back(self):
        """背视图。"""
        self._apply_view_direction((0, -1, 0), (0, 0, 1))

    def view_left(self):
        """左视图。"""
        self._apply_view_direction((-1, 0, 0), (0, 0, 1))

    def view_right(self):
        """右视图。"""
        self._apply_view_direction((1, 0, 0), (0, 0, 1))

    def view_top(self):
        """俯视图（平面视图）。"""
        self._apply_view_direction((0, 0, 1), (0, 1, 0))

    def view_bottom(self):
        """仰视图。"""
        self._apply_view_direction((0, 0, -1), (0, 1, 0))

    # ------------------------------------------------------------------ #
    #  相机重置
    # ------------------------------------------------------------------ #
    def reset_zoom(self):
        """只重置缩放（Dolly），不改变相机方向和焦点。"""
        self._renderer.ResetCamera()
        self._renderer.ResetCameraClippingRange()
        self.refresh()

    def reset_camera(self):
        """完全重置相机到默认正等轴视角。"""
        cam = self._renderer.GetActiveCamera()
        self._renderer.ResetCamera()
        cam.SetPosition(1, 1, 1)
        cam.SetFocalPoint(0, 0, 0)
        cam.SetViewUp(0, 0, 1)
        cam.OrthogonalizeViewUp()
        self._renderer.ResetCamera()
        self._renderer.ResetCameraClippingRange()
        self.refresh()

    # ------------------------------------------------------------------ #
    #  刷新
    # ------------------------------------------------------------------ #
    def refresh(self):
        """触发渲染刷新。"""
        self.GetRenderWindow().Render()
