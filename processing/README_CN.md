# Processing 目录 - 代码运行逻辑

## 📋 概述

`/processing/` 目录包含 AgentMove 框架的数据处理流程。该流程将原始轨迹数据转换为适合下一位置预测任务的格式。处理过程包括下载数据、提取特定城市的轨迹、使用地址信息丰富数据，以及为模型训练和评估准备数据。

## 🔄 数据处理流程

完整的数据处理工作流按以下顺序执行：

```
1. download.py          → 下载原始数据集
2. process_*.py         → 提取和过滤城市特定轨迹  
3. osm_address_*.py     → 从 OpenStreetMap 获取地址信息
4. trajectory_address_match.py → 将轨迹与结构化地址匹配
5. data.py              → 最终预处理（由 agent.py 自动调用）
```

---

## 📁 文件说明和运行逻辑

### 1. `download.py` - 数据集下载器

**功能**: 从各种来源下载原始移动数据集。

**支持的数据集**:
- `tsmc2014`: TSMC 2014 的 Foursquare 签到数据
- `tist2015`: TIST 2015 的 Foursquare 签到数据
- `www2019`: WWW 2019 的 ISP 轨迹数据
- `gowalla`: Gowalla 签到数据

**主要函数**:
- `download_data(data_name, use_proxy)`: 主下载函数
  - 从 URL 下载数据集
  - 解压压缩文件（zip/gz）
  - 将数据放置在适当的目录中
  - 支持代理以访问受限网络

**使用方法**:
```bash
python -m processing.download --data_name=www2019 --use_proxy
```

**输出**: `data/` 子目录中的原始数据集文件

---

### 2. `process_fsq_city_data.py` - Foursquare 城市数据处理器

**功能**: 处理全球 Foursquare 签到数据并提取特定城市的轨迹。

**执行逻辑**:

1. **加载城市信息**: 
   - 从 `dataset_TIST2015_Cities.txt` 读取城市坐标
   - 创建城市名称到坐标的映射

2. **加载 POI 数据**:
   - 读取 POI 信息（ID、位置、类别）
   - 对于 TIST2015: `dataset_TIST2015_POIs.txt`
   - 对于 Gowalla: `gowalla_totalCheckins.txt`

3. **计算距离**（使用 haversine 公式）:
   - 计算每个 POI/签到到所有城市的距离
   - 使用 PyTorch 进行高效的批量计算
   - 将每个 POI 分配给最近的城市

4. **按城市过滤**:
   - 对于 `EXP_CITIES` 中的每个城市，过滤相关的签到
   - 提取用户、时间、地点、位置和类别

5. **输出**:
   - 保存城市特定数据: `{city_name}_filtered.csv`
   - 列: `city, user, time, venue_id, utc_time, longitude, latitude, venue_cat_name`

**关键函数**: `haversine_torch()` - 使用 PyTorch 进行快速距离计算

**使用方法**:
```bash
python -m processing.process_fsq_city_data
```

**输出**: `data/no_address_traj/{city}_filtered.csv`

---

### 3. `process_isp_shanghai.py` - ISP 轨迹处理器

**功能**: 处理上海的原始 ISP（电信）轨迹数据，并将其与 POI 类别匹配。

**执行逻辑**:

1. **加载 POI 类别**:
   - 函数: `load_cat()`
   - 读取 `poi.txt`，包含 POI 名称、位置和类别
   - 构建 KDTree 用于快速空间查找
   - 创建映射: POI ID → (位置, 类别, 名称)

2. **采样用户**:
   - 函数: `samples_generator()`
   - 按轨迹长度选择前 2000 个用户
   - 确保足够的数据质量

3. **处理 ISP 数据**（密集、频繁签到）:
   - 函数: `load_data_match_cat_telecom()`
   - 解析格式: `user_id\ttimestamp,venue_id,lon_lat|...`
   - 使用 KDTree 将坐标匹配到最近的 POI
   - 按天分组（8am-8pm 过滤）
   - 可选压缩: `dense_session_compress()` 删除冗余停留点

4. **处理微博数据**（稀疏、社交媒体签到）:
   - 函数: `load_data_match_sparse_cat()`
   - 类似于 ISP 但不同的会话定义
   - 按 24 小时窗口分组，每个会话最多 20 个点

5. **输出**:
   - `Shanghai_filtered.csv`: 密集 ISP 轨迹
   - `Shanghai_Weibo_filtered.csv`: 稀疏微博轨迹

**关键算法**: 会话压缩删除 2 小时窗口内的连续重复位置

**使用方法**:
```bash
python -m processing.process_isp_shanghai
```

**输出**: `data/no_address_traj/Shanghai*.csv`

---

### 4. `osm_address_deploy.py` - 地址解析（部署服务）

**功能**: 使用自部署的 Nominatim 服务为轨迹数据添加 OpenStreetMap 地址信息，用于大规模并行处理。

**执行逻辑**:

1. **加载地点坐标**:
   - 读取所有 `{city}_filtered.csv` 文件
   - 提取唯一的 `(venue_id, longitude, latitude)` 元组

2. **反向地理编码**:
   - 函数: `reverse_geocode_v2()`
   - 调用部署的 Nominatim 服务器: `http://{server}/reverse`
   - 参数: lat, lon, zoom=18, language=en-US
   - 返回结构化地址 JSON

3. **并行处理**:
   - 函数: `process_map_v2()`
   - 使用 `multiprocessing.Pool`，可配置工作进程数
   - 同时处理多个地点以提高速度

4. **输出格式**:
   - 保存: `data/nominatim/{city}.csv`
   - 列: `city, venue_id, Lng, Lat, address`
   - 地址是 JSON 字符串，结构: `{"road": "...", "suburb": "...", ...}`

**配置**:
- `NOMINATIM_DEPLOY_SERVER`: 服务器 IP 和端口（来自环境变量）
- `NOMINATIM_DEPLOY_WORKERS`: 并行工作进程数（默认: 10）

**使用方法**:
```bash
# 需要部署 Nominatim 服务
python -m processing.osm_address_deploy
```

**输出**: `data/nominatim/{city}.csv`

---

### 5. `osm_address_web.py` - 地址解析（Web API）

**功能**: `osm_address_deploy.py` 的替代方案，使用官方 Nominatim web API 进行小规模测试。

**执行逻辑**:
- 类似于 `osm_address_deploy.py`，但：
  - 使用 `geopy.Nominatim` 客户端
  - 速率限制（1 次请求/秒）
  - 单线程处理
  - 适合小数据集或测试

**区别**:
- **Deploy**: 快速、并行、需要服务器设置
- **Web**: 慢速、顺序、无需设置

**使用方法**:
```bash
python -m processing.osm_address_web
```

**输出**: `data/nominatim/{city}_address.txt`

---

### 6. `trajectory_address_match.py` - 地址结构统一

**功能**: 使用 LLM 解析将原始 OSM 地址转换为标准化的 4 级层次结构。

**执行逻辑**:

1. **加载原始地址**:
   - 从 `data/nominatim/` 读取 CSV 文件
   - 每行: `city, venue_id, longitude, latitude, address_json`

2. **基于 LLM 的地址解析**:
   - 函数: `get_response(address)`
   - 将地址字符串发送给 LLM（在 `ADDRESS_L4_FORMAT_MODEL` 中配置）
   - 提示: "提取行政区域、街道办事处、POI 名称、街道名称"
   - 返回结构化 JSON

3. **并行处理**:
   - 类: `Saver` - 线程安全的文件写入器
   - 使用 `ThreadPoolExecutor` 进行并发 LLM 调用
   - 可配置工作进程: `ADDRESS_L4_WORKERS`

4. **地址匹配**:
   - 加载轨迹数据: `{city}_filtered.csv`
   - 创建键: `{city}_{venue_id}`
   - 与解析的地址字典匹配
   - 添加 4 个地址列: `admin, subdistrict, poi, street`

5. **输出结构**:
   - 中间结果: `data/address_l4/{city}_addr_dict.json`
   - 最终结果: `data/city_data/{city}_filtered.csv`
   - 最终列: `city, user, time, venue_id, utc_time, longitude, latitude, venue_cat_name, admin, subdistrict, poi, street`

**4 级地址层次结构**:
```
第1级: administrative   (例如: "浦东新区", "Manhattan")
第2级: subdistrict      (例如: "陆家嘴街道", "Upper East Side")
第3级: poi              (例如: "东方明珠", "Central Park")
第4级: street           (例如: "世纪大道", "5th Avenue")
```

**使用方法**:
```bash
python -m processing.trajectory_address_match
```

**输出**: `data/city_data/{city}_filtered.csv`（带地址列）

---

### 7. `data.py` - 最终数据预处理

**功能**: 模型训练的主要数据加载器和预处理器。由 `agent.py` 自动调用。

**执行逻辑**:

#### 类: `Dataset`

**初始化参数**:
- `dataset_name`: 城市名称（例如: "nyc", "Shanghai"）
- `trajectory_mode`: "user_split" 或 "trajectory_split"
- `historical_stays`: 历史访问次数（默认: 40）
- `context_stays`: 上下文访问次数（默认: 6）
- `traj_min_len`: 最小轨迹长度
- `traj_max_len`: 最大轨迹长度
- `train_sample`: 训练数据比例（0.7, 0.5, 0.3, 0.1）
- `test_sample`: 测试轨迹数量（默认: 200）

#### 主要处理步骤:

**1. 加载数据集** (`get_dataset()`):
- 读取 `data/city_data/{city}_filtered.csv`
- 提取特征: 时间、位置、类别、地址
- 创建日期时间特征: 小时、星期、AM/PM
- 将地点 ID 映射到整数
- 平均每个地点的坐标

**2. 计算轨迹** (`get_trajectories()`):

   **A. 轨迹分割**（默认模式）:
   - 按用户分组签到
   - 使用 72 小时时间窗口分割轨迹
   - 分配唯一的全局轨迹 ID（`DL_traj_id`）
   
   **B. 训练/验证/测试分割**:
   - **标准数据集**（NYC, Tokyo）:
     - 训练: 70% 的轨迹
     - 验证: 10% 的轨迹
     - 测试: 20% 的轨迹
   - **上海 ISP**（WWW2019）:
     - 训练: 40% 的轨迹
     - 验证: 10% 的轨迹
     - 测试: 50% 的轨迹
   
   **C. 对于每个测试轨迹**:
   - 历史数据: 来自训练轨迹的所有签到
   - 上下文数据: 测试轨迹中除最后一个签到外的所有签到
   - 目标: 最后一个签到（预测目标）
   - 真实值: 实际地点 ID 和地址

**3. 创建测试字典**:
```python
test_dictionary[user_id][trajectory_id] = {
    'historical_stays': [[hour, weekday, category, venue_id, admin, subdistrict, poi, street], ...],
    'historical_pos': [[longitude, latitude], ...],
    'historical_addr': [[admin, subdistrict, poi, street], ...],
    'context_stays': [[hour, weekday, category, venue_id, admin, subdistrict, poi, street], ...],
    'context_pos': [[longitude, latitude], ...],
    'context_addr': [[admin, subdistrict, poi, street], ...],
    'target_stay': [hour, weekday, '<next_place_id>', '<next_place_address>']
}

true_locations[user_id][trajectory_id] = {
    'ground_stay': "venue_id",
    'ground_pos': [longitude, latitude],
    'ground_addr': [admin, subdistrict, poi, street]
}
```

**4. 生成基线数据** (`get_baseline()`):
- 用于深度学习基线（STHM, GETNext, SNPM）
- 编码分类变量
- 分割为训练/验证/测试 CSV
- 保存到 `baselines/{model}/dataset/`

**5. 保存处理后的数据**:
- `data/processed/test_dictionary_{city}_{mode}.json`
- `data/processed/true_locations_{city}_{mode}.json`
- `data/processed/align_locations_{city}_{mode}.json`

**关键方法**:
- `get_encode()`: 深度学习的标签编码
- `test_traj_sampling()`: 采样测试轨迹
- `train_traj_sampling()`: 采样训练轨迹

**使用方法**: 运行时自动调用:
```bash
python -m agent --city_name=Shanghai ...
```

**输出**: `data/processed/` 中的 JSON 文件

---

### 8. `convert.py` - 格式转换器

**功能**: 将制表符分隔的地址文件转换为 CSV 格式的简单工具。

**逻辑**:
- 读取: `data/nominatim/New York_address2.txt`（TSV）
- 转换为: `data/nominatim/New York.csv`（CSV）
- 列: `city, place_id, lon, lat, address`

**使用方法**: 独立脚本用于格式转换
```bash
python processing/convert.py
```

---

## 📊 数据流程图

```
原始数据集
    ↓
[download.py] → 下载数据集
    ↓
原始签到数据
    ↓
[process_fsq_city_data.py] → 提取城市轨迹
[process_isp_shanghai.py]  → 处理 ISP 数据
    ↓
城市轨迹（无地址）
{city}_filtered.csv: city, user, time, venue_id, utc_time, lon, lat, venue_cat_name
    ↓
[osm_address_deploy.py] → 获取 OSM 地址
[osm_address_web.py]
    ↓
原始地址数据
{city}.csv: city, venue_id, lon, lat, address_json
    ↓
[trajectory_address_match.py] → 解析和结构化地址
    ↓
丰富的轨迹
{city}_filtered.csv: + admin, subdistrict, poi, street
    ↓
[data.py] → 分割并为模型准备
    ↓
处理后的数据
test_dictionary_{city}.json
true_locations_{city}.json
```

---

## 🎯 执行顺序

完整的预处理流程，按此顺序执行：

```bash
# 1. 在 config.py 中配置城市
# EXP_CITIES = ["Shanghai", "Tokyo", "NewYork", ...]

# 2. 下载原始数据
python -m processing.download --data_name=www2019

# 3. 处理城市特定轨迹
# 对于 Foursquare 数据集:
python -m processing.process_fsq_city_data
# 对于上海 ISP:
python -m processing.process_isp_shanghai

# 4. 从 OpenStreetMap 获取地址
# 需要部署的 Nominatim 服务:
python -m processing.osm_address_deploy
# 或使用 web API（较慢）:
python -m processing.osm_address_web

# 5. 匹配和结构化地址
python -m processing.trajectory_address_match

# 6. 最终预处理（自动）
# 运行实验时由 agent.py 调用
python -m agent --city_name=Shanghai ...
```

---

## 🔧 配置

关键配置变量（在 `config.py` 中）:

- `EXP_CITIES`: 要处理的城市列表
- `DATASET`: 数据集类型（"TIST2015", "gowalla", "www2019"）
- `CITY_DATA_DIR`: 处理后数据的输出目录
- `NOMINATIM_PATH`: 地址数据目录
- `NOMINATIM_DEPLOY_SERVER`: Nominatim 服务地址
- `NOMINATIM_DEPLOY_WORKERS`: 地址获取的并行工作进程数
- `ADDRESS_L4_FORMAT_MODEL`: 用于地址解析的 LLM 模型
- `ADDRESS_L4_WORKERS`: LLM 调用的并行工作进程数

---

## 📝 输出数据模式

### 中间文件

**`{city}_filtered.csv`（步骤 3 之后）**:
```csv
city,user,time,venue_id,utc_time,longitude,latitude,venue_cat_name
Shanghai,12345,480,venue_001,Tue Apr 03 18:28:06 2016,121.44,31.03,Restaurant
```

**`{city}.csv`（步骤 4 之后）**:
```csv
city,venue_id,Lng,Lat,address
Shanghai,venue_001,121.44,31.03,"{\"road\":\"...\",\"suburb\":\"...\"}"
```

**`{city}_filtered.csv`（步骤 5 之后，最终）**:
```csv
city,user,time,venue_id,utc_time,longitude,latitude,venue_cat_name,admin,subdistrict,poi,street
Shanghai,12345,480,venue_001,Tue Apr 03 18:28:06 2016,121.44,31.03,Restaurant,浦东新区,陆家嘴,金茂大厦,世纪大道
```

### 最终处理文件

**`test_dictionary_{city}_trajectory_split.json`**:
```json
{
  "user_id": {
    "trajectory_id": {
      "historical_stays": [[hour, weekday, category, venue_id, admin, subdistrict, poi, street], ...],
      "context_stays": [[hour, weekday, category, venue_id, admin, subdistrict, poi, street], ...],
      "target_stay": [hour, weekday, "<next_place_id>", "<next_place_address>"]
    }
  }
}
```

**`true_locations_{city}_trajectory_split.json`**:
```json
{
  "user_id": {
    "trajectory_id": {
      "ground_stay": "venue_id",
      "ground_pos": [longitude, latitude],
      "ground_addr": [admin, subdistrict, poi, street]
    }
  }
}
```

---

## ⚙️ 依赖项

使用的主要 Python 包:

- `pandas`: 数据处理
- `numpy`: 数值运算
- `torch`: GPU 加速的距离计算
- `sklearn`: 空间查询的 KDTree、训练/测试分割
- `geopy`: 地理编码（web API）
- `requests`: HTTP 请求（部署服务）
- `tqdm`: 进度条
- `json_repair`: 健壮的 JSON 解析
- `multiprocessing`/`ThreadPoolExecutor`: 并行处理

---

## 🐛 调试技巧

1. **检查数据路径**: 确保 `config.py` 中的路径与您的目录结构匹配
2. **验证 API 密钥**: 在 `.bashrc` 中设置基于 LLM 的地址解析所需的密钥
3. **使用小数据集测试**: 设置 `EXP_CITIES = ["Tokyo"]` 以加快迭代速度
4. **监控内存**: 大城市可能需要大量 RAM
5. **检查 Nominatim 服务**: 验证 `NOMINATIM_DEPLOY_SERVER` 是否可访问
6. **检查中间输出**: 在每个步骤后检查 CSV 文件

---

## 🔍 常见问题

**问题**: "Dataset already present"（数据集已存在）
- **解决方案**: 如果要重新下载，删除现有文件

**问题**: Nominatim 超时错误
- **解决方案**: 减少 `NOMINATIM_DEPLOY_WORKERS` 或增加超时时间

**问题**: LLM 解析失败
- **解决方案**: 检查 API 密钥、网络代理或 LLM 可用性

**问题**: 过滤后轨迹为空
- **解决方案**: 检查 `traj_min_len`、`traj_max_len` 参数

---

## 📚 参考

- Nominatim Docker: https://github.com/mediagis/nominatim-docker
- OpenStreetMap Nominatim API: https://nominatim.org/
- AgentMove 论文: https://arxiv.org/abs/2408.13986

---

## 📞 联系方式

有关处理流程的问题，请参阅主 README 或联系作者。
