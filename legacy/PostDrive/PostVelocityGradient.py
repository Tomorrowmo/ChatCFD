from PostDrive.VelocityGradientStruct import *
import vtk

class PostVelocityGradient:
    def __init__(self):
        pass

    '''计算速度梯度'''
    def CulVelocityGradient(self,multiBlockDataSet:vtk.vtkMultiBlockDataSet,velocityGradientStruct:VelocityGradientStruct):
        num_blocks = multiBlockDataSet.GetNumberOfBlocks()
        for block_idx in range(num_blocks):
            block = multiBlockDataSet.GetBlock(block_idx)
            if block is None:
                continue
            #block_name = multiBlockDataSet.GetMetaData(block_idx).Get(vtk.vtkCompositeDataSet.NAME())
            res = self.CulVelocityGradientSingle(block,velocityGradientStruct)
            multiBlockDataSet.SetBlock(block_idx,res)

    def CulVelocityGradientSingle(self,PointSet:vtk.vtkPointSet,velocityGradientStruct:VelocityGradientStruct):
        #vtk 计算速度梯度的 filter，输入是 vtkPointSet，输出也是 vtkPointSet，包含速度梯度、涡量、压力系数等结果。
        calculateVelocityGradient = vtk.CalculateVelocityGradient()
        calculateVelocityGradient.SetInputData(PointSet)
        #设置参数
        calculateVelocityGradient.SetScalarThreeComponent(velocityGradientStruct.velocity_x,velocityGradientStruct.velocity_y,velocityGradientStruct.velocity_z)
        calculateVelocityGradient.SetPressureName(velocityGradientStruct.pressure)
        calculateVelocityGradient.SetDensityName(velocityGradientStruct.density)
        calculateVelocityGradient.SetSpecificHeatRatio(velocityGradientStruct.specific_heat_ratio)
        calculateVelocityGradient.SetResultVelocityGradientName(velocityGradientStruct.result_velocity_gradient)
        calculateVelocityGradient.SetResultVorticityName(velocityGradientStruct.result_vorticity)
        calculateVelocityGradient.SetResultVelocityName(velocityGradientStruct.result_velocity)
        calculateVelocityGradient.SetResultCpName(velocityGradientStruct.result_cp)
        calculateVelocityGradient.SetResultSoundSpeedName(velocityGradientStruct.result_sound_speed)
        calculateVelocityGradient.SetResultMachNumber(velocityGradientStruct.result_mach_number)
        calculateVelocityGradient.SetReferenceData(velocityGradientStruct.p_inf,velocityGradientStruct.rho_inf,velocityGradientStruct.U_inf)
        calculateVelocityGradient.SetCulVelocityGradient(velocityGradientStruct.velocity_gradient_switch)
        calculateVelocityGradient.SetCulVorticity(velocityGradientStruct.vorticity_switch)
        calculateVelocityGradient.SetCulPressureCoefficient(velocityGradientStruct.pressure_coefficient_switch)
        calculateVelocityGradient.SetCulVelocityAmplitude(velocityGradientStruct.velocity_amplitude_switch)
        calculateVelocityGradient.SetCulSoundSpeed(velocityGradientStruct.sund_speed_switch)
        calculateVelocityGradient.SetCulMach(velocityGradientStruct.mach_switch)
        calculateVelocityGradient.Updata()
        return calculateVelocityGradient.getOutput()