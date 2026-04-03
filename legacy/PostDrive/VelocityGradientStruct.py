class VelocityGradientStruct:
    def __init__(self):
        #速度
        self.velocity_x = 'velocity_x'
        self.velocity_y = 'velocity_y'
        self.velocity_z = 'velocity_z'
        #算法开关
        self.velocity_gradient_switch = True
        self.vorticity_switch = False
        self.pressure_coefficient_switch = False
        self.velocity_amplitude_switch = False
        self.sund_speed_switch = False
        self.mach_switch = False
        #压力
        self.pressure = "Pressure"
        #密度
        self.density = "Density"
        #比热比与介质相关
        self.specific_heat_ratio = 1.4
        #速度梯度结果名
        self.result_velocity_gradient = "VelocityGradient"
        #涡量
        self.result_vorticity = "Vorticity"
        #压力系数
        self.result_cp = "PressureCoefficient"
        #速度
        self.result_velocity = "Velocity"
        #声速
        self.result_sound_speed = "SoundSpeed"
        #马赫数
        self.result_mach_number = "MachNumber"
        #参考系数
        self.p_inf = 101325 
        self.rho_inf = 1.225
        self.U_inf = 50