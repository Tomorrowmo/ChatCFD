from PostDrive.ForceMomentIntegralStruct import *
import vtk

class PostIntegral:
    def __init__(self):
        pass

    def forceMomentIntegtal(self,multiBlockDataSet:vtk.vtkMultiBlockDataSet,forceMoment:ForceMoment,zoneName = ''):
        """力与力矩积分,多块选择计算,zoneName为空合并计算整体"""
        pointSet = None
        #合并数据
        if len(zoneName)<=0:
            AppendFilter = vtk.vtkAppendFilter()
            num_blocks = multiBlockDataSet.GetNumberOfBlocks()
            for block_idx in range(num_blocks):
                block = multiBlockDataSet.GetBlock(block_idx)
                AppendFilter.AddInputData(block)
            AppendFilter.Update()
            pointSet=AppendFilter.GetOutput()
        else:
            #单个数据
            num_blocks = multiBlockDataSet.GetNumberOfBlocks()
            for block_idx in range(num_blocks):
                block = multiBlockDataSet.GetBlock(block_idx)
                if block is None:
                    continue
                block_name = multiBlockDataSet.GetMetaData(block_idx).Get(vtk.vtkCompositeDataSet.NAME())
                if zoneName==block_name:
                    pointSet = block
                    break
        return self.forceMomentIntegtalSingle(pointSet,forceMoment)

    def forceMomentIntegtalSingle(self,PointSet:vtk.vtkPointSet,forceMoment:ForceMoment) -> ForceMomentRes:
        """计算单个数据力和力矩"""
        forceMomentIntegtal = vtk.ForceMomentIntegtal()
        forceMomentIntegtal.SetInputData(PointSet)
        forceMomentIntegtal.SetPressureName(forceMoment.pressure)
        forceMomentIntegtal.SetFlipNormals(forceMoment.flip_normals)
        forceMomentIntegtal.SetReferenceCondition(forceMoment.density,forceMoment.velocity,forceMoment.refArea,forceMoment.refLength)
        forceMomentIntegtal.SetReferencePoint(forceMoment.reference_point_x,forceMoment.reference_point_y,forceMoment.reference_point_z)
        forceMomentIntegtal.SetAngles(forceMoment.alpha_angle,forceMoment.beta_angle)
        forceMomentIntegtal.SetShearForce(forceMoment.shear_force_x,forceMoment.shear_force_y,forceMoment.shear_force_z)
        forceMomentIntegtal.Updata()
        forceMomentRes = ForceMomentRes()
        #力
        forceMomentRes.force_x = forceMomentIntegtal.GetTotalForceX()
        forceMomentRes.force_y = forceMomentIntegtal.GetTotalForceY()
        forceMomentRes.force_z = forceMomentIntegtal.GetTotalForceZ()
        #力矩
        forceMomentRes.moment_x = forceMomentIntegtal.GetTotalMomentX()
        forceMomentRes.moment_y = forceMomentIntegtal.GetTotalMomentY()
        forceMomentRes.moment_z = forceMomentIntegtal.GetTotalMomentZ()
        #升力系数
        forceMomentRes.lift_coefficient = forceMomentIntegtal.GetLiftCoefficient()
        #阻力系数
        forceMomentRes.drag_coefficient = forceMomentIntegtal.GetDragCoefficient()
        #侧向力系数CZ
        forceMomentRes.side_force_coefficient = forceMomentIntegtal.GetSideForceCoefficient()
        #俯仰力矩系数CM
        forceMomentRes.pitch_moment_coefficient = forceMomentIntegtal.GetPitchingMomentCoefficient()
        #偏航力矩系数CN
        forceMomentRes.yaw_moment_coefficient = forceMomentIntegtal.GetYawingMomentCoefficient()
        #滚转力矩系数CL
        forceMomentRes.roll_moment_coefficient = forceMomentIntegtal.GetRollingMomentCoefficient()
        return forceMomentRes
