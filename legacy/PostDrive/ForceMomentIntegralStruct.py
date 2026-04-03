#
class ForceMoment:
    def __init__(self):
        #参考点位置，非必须
        self.reference_point_x = 0.0
        self.reference_point_y = 0.0
        self.reference_point_z = 0.0
        #剪切力名称粘性必须，三分量
        self.shear_force_x = ''
        self.shear_force_y = ''
        self.shear_force_z = ''
        #压力名
        self.pressure = 'Pressure'
        #法向量是否取反
        self.flip_normals = True
        #风轴，非必须，攻角和侧滑角
        self.alpha_angle = 0.0
        self.beta_angle = 0.0
        #参考条件
        self.density = 1.225 #来流密度
        self.velocity = 1.0  #速度
        self.refArea = 1.0   #参考面积
        self.refLength = 1.0 #参考长度

class ForceMomentRes:
    def __init__(self):
        #力
        self.force_x = 0.0
        self.force_y = 0.0
        self.force_z = 0.0
        #力矩
        self.moment_x = 0.0
        self.moment_y = 0.0
        self.moment_z = 0.0
        self.lift_coefficient = 0.0 #升力系数
        self.drag_coefficient = 0.0 #阻力系数
        self.side_force_coefficient = 0.0 #侧向力系数
        self.pitch_moment_coefficient = 0.0 #俯仰力矩系数
        self.yaw_moment_coefficient = 0.0 #偏航力矩系数
        self.roll_moment_coefficient = 0.0 #滚转力矩系数