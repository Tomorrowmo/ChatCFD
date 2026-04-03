import vtk


def getPostInfo(MultiBlockDataSet: vtk.vtkMultiBlockDataSet) -> dict:
    """获取后处理文件信息"""
    # 块级数据列表
    blocks_info = []

    # 聚合数据初始化
    total_points = 0
    total_cells = 0
    overall_bounds = [
        float("inf"),
        float("-inf"),
        float("inf"),
        float("-inf"),
        float("inf"),
        float("-inf"),
    ]
    scalar_ranges = []  # 存储每个标量的全局范围 {标量名: {"min": ..., "max": ...}}

    # 遍历每个块
    num_blocks = MultiBlockDataSet.GetNumberOfBlocks()
    for block_idx in range(num_blocks):
        block = MultiBlockDataSet.GetBlock(block_idx)
        block_name = MultiBlockDataSet.GetMetaData(block_idx).Get(
            vtk.vtkCompositeDataSet.NAME()
        )

        if block is None:
            continue

        block_info = {}

        # 块名称
        block_info["name"] = block_name if block_name else f"Block_{block_idx}"

        # 获取块的几何数据
        if isinstance(block, vtk.vtkDataSet):
            # 单元数和顶点数
            block_info["单元数"] = block.GetNumberOfCells()
            block_info["顶点数"] = block.GetNumberOfPoints()

            # 总数累加
            total_cells += block.GetNumberOfCells()
            total_points += block.GetNumberOfPoints()

            # 单元类型
            if block.GetNumberOfCells() > 0:
                cell = block.GetCell(0)
                block_info["单元类型"] = cell.GetClassName()

            # 包围盒 (bounds)
            bounds = block.GetBounds()
            block_info["包围盒"] = {
                "xmin": bounds[0],
                "xmax": bounds[1],
                "ymin": bounds[2],
                "ymax": bounds[3],
                "zmin": bounds[4],
                "zmax": bounds[5],
            }

            # 更新整体包围盒
            overall_bounds[0] = min(overall_bounds[0], bounds[0])
            overall_bounds[1] = max(overall_bounds[1], bounds[1])
            overall_bounds[2] = min(overall_bounds[2], bounds[2])
            overall_bounds[3] = max(overall_bounds[3], bounds[3])
            overall_bounds[4] = min(overall_bounds[4], bounds[4])
            overall_bounds[5] = max(overall_bounds[5], bounds[5])

            # 标量信息
            scalars_infos = []
            point_data = block.GetPointData()
            cell_data = block.GetCellData()

            # 提取点数据的标量
            if point_data and point_data.GetNumberOfArrays() > 0:
                for array_idx in range(point_data.GetNumberOfArrays()):
                    array = point_data.GetArray(array_idx)
                    if array is None:
                        continue

                    array_name = (
                        array.GetName()
                        if array.GetName()
                        else f"PointArray_{array_idx}"
                    )

                    # 验证数组有效性
                    if array.GetNumberOfTuples() == 0:
                        continue

                    # 计算标量的min/max
                    try:
                        array_range = array.GetRange()
                        # 检查范围是否有效
                        if array_range is not None and len(array_range) >= 2:
                            scalars_info = {
                                "name": array_name,
                                "min": float(array_range[0]),
                                "max": float(array_range[1]),
                                "位置": "顶点上",
                            }
                            scalars_infos.append(scalars_info)
                            # 更新全局范围，避免重复
                            bfind = False
                            for scalar_range_obj in scalar_ranges:
                                scalar_range_name = scalar_range_obj["name"]
                                if scalar_range_name == array_name:
                                    scalar_range_obj["min"] = min(
                                        scalar_range_obj["min"], float(array_range[0])
                                    )
                                    scalar_range_obj["max"] = max(
                                        scalar_range_obj["max"], float(array_range[1])
                                    )
                                    bfind = True
                                    break
                            if bfind is False:
                                scalar_ranges.append(
                                    {
                                        "name": array_name,
                                        "min": float(array_range[0]),
                                        "max": float(array_range[1]),
                                    }
                                )
                    except Exception as e:
                        # 跳过无法获取范围的数组
                        continue

            # 提取单元数据的标量
            if cell_data and cell_data.GetNumberOfArrays() > 0:
                for array_idx in range(cell_data.GetNumberOfArrays()):
                    array = cell_data.GetArray(array_idx)
                    if array is None:
                        continue

                    array_name = (
                        array.GetName() if array.GetName() else f"CellArray_{array_idx}"
                    )

                    # 验证数组有效性
                    if array.GetNumberOfTuples() == 0:
                        continue

                    # 计算标量的min/max
                    try:
                        array_range = array.GetRange()
                        # 检查范围是否有效
                        if array_range is not None and len(array_range) >= 2:
                            # 如果标量已存在于PointData中，则跳过
                            existing_names = [s["name"] for s in scalars_infos]
                            if array_name not in existing_names:
                                scalars_info = {
                                    "name": array_name,
                                    "min": float(array_range[0]),
                                    "max": float(array_range[1]),
                                    "位置": "单元上",
                                }
                                scalars_infos.append(scalars_info)
                            # 更新全局范围，避免重复
                            bfind = False
                            for scalar_range_obj in scalar_ranges:
                                scalar_range_name = scalar_range_obj["name"]
                                if scalar_range_name == array_name:
                                    scalar_range_obj["min"] = min(
                                        scalar_range_obj["min"], float(array_range[0])
                                    )
                                    scalar_range_obj["max"] = max(
                                        scalar_range_obj["max"], float(array_range[1])
                                    )
                                    bfind = True
                                    break
                            if bfind is False:
                                scalar_ranges.append(
                                    {
                                        "name": array_name,
                                        "min": float(array_range[0]),
                                        "max": float(array_range[1]),
                                    }
                                )
                    except Exception as e:
                        # 跳过无法获取范围的数组
                        continue

            block_info["物理量"] = scalars_infos

        blocks_info.append(block_info)

    # 构建最终的JSON结果
    result = {
        "区域": blocks_info,
        "整体": {
            "顶点数": total_points,
            "单元数": total_cells,
            "包围盒": {
                "xmin": overall_bounds[0],
                "xmax": overall_bounds[1],
                "ymin": overall_bounds[2],
                "ymax": overall_bounds[3],
                "zmin": overall_bounds[4],
                "zmax": overall_bounds[5],
            },
            "物理量": scalar_ranges,
        },
    }
    return result
