from typing import List

import vtk
from enum import Enum


class Range:
    def __init__(self, min_value: float, max_value: float):
        self.min_value = min_value
        self.max_value = max_value


class PhysicalType(Enum):
    Scalar = 1       # 名称: 值
    Vector = 2


class Physical:
    def __init__(self):
        self.name = ""
        self.type = PhysicalType.Scalar
        self.range = Range(0, 0)
        self.ranges: list[Range] = []  # 对于矢量数据,每个分量的范围

    def GetRange(self):
        if self.type == PhysicalType.Scalar:
            return self.range
        elif self.type == PhysicalType.Vector:
            return self.ranges
        else:
            return None


class BlockData:
    def __init__(self, name: str, vtkdata: vtk.vtkPointSet):
        self.name = name
        self.vtkdata = vtkdata
        self.physicals: dict[str, Physical] = {}


def _collectFromBlock(
        block: vtk.vtkPointSet,
        physicals: dict[str, Physical]):
    """从块的 PointData 和 CellData 中收集物理量范围,结果写入 physicals"""
    for attribute_data in (block.GetPointData(), block.GetCellData()):
        if attribute_data is None:
            continue
        for arr_idx in range(attribute_data.GetNumberOfArrays()):
            array: vtk.vtkDataArray = attribute_data.GetArray(arr_idx)
            if array is None:
                continue
            name = array.GetName()
            if name is None:
                continue
            num_components = array.GetNumberOfComponents()
            if name not in physicals:
                physical = Physical()
                physical.name = name
                if num_components == 1:
                    physical.type = PhysicalType.Scalar
                    physical.range = Range(*array.GetRange(0))
                elif num_components == 3:
                    physical.type = PhysicalType.Vector
                    physical.ranges = [Range(*array.GetRange(c))
                                       for c in range(num_components)]
                else:
                    # 目前只处理标量和三维矢量,其他类型暂不支持
                    continue
                physicals[name] = physical
            else:
                physical = physicals[name]
                if physical.type == PhysicalType.Scalar:
                    r = array.GetRange(0)
                    physical.range.min_value = min(
                        physical.range.min_value, r[0])
                    physical.range.max_value = max(
                        physical.range.max_value, r[1])
                else:
                    for c in range(num_components):
                        r = array.GetRange(c)
                        physical.ranges[c].min_value = min(
                            physical.ranges[c].min_value, r[0])
                        physical.ranges[c].max_value = max(
                            physical.ranges[c].max_value, r[1])


def _mergePhysicals(src: dict[str, Physical], dst: dict[str, Physical]):
    """将 src 中的物理量合并到 dst"""
    for name, sp in src.items():
        if name not in dst:
            p = Physical()
            p.name = sp.name
            p.type = sp.type
            if sp.type == PhysicalType.Scalar:
                p.range = Range(sp.range.min_value, sp.range.max_value)
            else:
                p.ranges = [Range(r.min_value, r.max_value) for r in sp.ranges]
            dst[name] = p
        else:
            dp = dst[name]
            if dp.type == PhysicalType.Scalar:
                dp.range.min_value = min(
                    dp.range.min_value, sp.range.min_value)
                dp.range.max_value = max(
                    dp.range.max_value, sp.range.max_value)
            else:
                for dr, sr in zip(dp.ranges, sp.ranges):
                    dr.min_value = min(dr.min_value, sr.min_value)
                    dr.max_value = max(dr.max_value, sr.max_value)


class MultiBlockDataSetAnalyse:
    def __init__(self):
        self.multi_block_data_set = None
        self.blocks: dict[str, BlockData] = {}
        self.physicals: dict[str, Physical] = {}

    def setMultiBlockDataSet(
            self,
            multi_block_data_set: vtk.vtkMultiBlockDataSet):
        self.multi_block_data_set = multi_block_data_set

    def Analyse(self):
        """分析多块数据集,获取每个块的名称和数据类型"""
        if self.multi_block_data_set is None:
            print("MultiBlockDataSet is not set.")
            return
        num_blocks = self.multi_block_data_set.GetNumberOfBlocks()
        for block_idx in range(num_blocks):
            block = self.multi_block_data_set.GetBlock(block_idx)
            if block is None:
                continue
            block_name = self.multi_block_data_set.GetMetaData(
                block_idx).Get(vtk.vtkCompositeDataSet.NAME())
            block_data = BlockData(block_name, block)
            self.blocks[block_name] = block_data
            _collectFromBlock(block_data.vtkdata, block_data.physicals)
            _mergePhysicals(block_data.physicals, self.physicals)


class MultiBlockDataSetAnalyses:
    def __init__(self):
        self.multi_block_data_sets: list[vtk.vtkMultiBlockDataSet] = []
        self.physicals: dict[str, Physical] = {}
        self.transient_data: List[dict[str, BlockData]] = []  # 每个时间步的块数据列表

    def setMultiBlockDataSets(
            self,
            multi_block_data_sets: list[vtk.vtkMultiBlockDataSet]):
        self.multi_block_data_sets = multi_block_data_sets

    def Analyse(self):
        """遍历所有 vtkMultiBlockDataSet,每个时间步独立解析并聚合全局最大最小值"""
        self.transient_data.clear()
        self.physicals.clear()
        for mbd in self.multi_block_data_sets:
            step_blocks: dict[str, BlockData] = {}
            num_blocks = mbd.GetNumberOfBlocks()
            for block_idx in range(num_blocks):
                block = mbd.GetBlock(block_idx)
                if block is None:
                    continue
                block_name = mbd.GetMetaData(block_idx).Get(
                    vtk.vtkCompositeDataSet.NAME())
                block_data = BlockData(block_name, block)
                _collectFromBlock(block_data.vtkdata, block_data.physicals)
                _mergePhysicals(block_data.physicals, self.physicals)
                step_blocks[block_name] = block_data
            self.transient_data.append(step_blocks)
        self.multi_block_data_sets.clear()
