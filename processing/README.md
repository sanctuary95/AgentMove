# Processing Directory - Code Execution Logic

## 📋 Overview

The `/processing/` directory contains the data processing pipeline for the AgentMove framework. This pipeline transforms raw trajectory data into a format suitable for next location prediction tasks. The processing involves downloading data, extracting city-specific trajectories, enriching them with address information, and preparing them for model training and evaluation.

## 🔄 Data Processing Pipeline

The complete data processing workflow follows these sequential steps:

```
1. download.py          → Download raw datasets
2. process_*.py         → Extract and filter city-specific trajectories  
3. osm_address_*.py     → Fetch address information from OpenStreetMap
4. trajectory_address_match.py → Match trajectories with structured addresses
5. data.py              → Final preprocessing (called automatically by agent.py)
```

---

## 📁 File Descriptions and Logic

### 1. `download.py` - Dataset Downloader

**Purpose**: Downloads raw mobility datasets from various sources.

**Supported Datasets**:
- `tsmc2014`: Foursquare check-in data from TSMC 2014
- `tist2015`: Foursquare check-in data from TIST 2015
- `www2019`: ISP trajectory data from WWW 2019
- `gowalla`: Gowalla check-in data

**Key Functions**:
- `download_data(data_name, use_proxy)`: Main download function
  - Downloads dataset from URL
  - Extracts compressed files (zip/gz)
  - Places data in appropriate directories
  - Supports proxy for restricted networks

**Usage**:
```bash
python -m processing.download --data_name=www2019 --use_proxy
```

**Output**: Raw dataset files in `data/` subdirectories

---

### 2. `process_fsq_city_data.py` - Foursquare City Data Processor

**Purpose**: Processes global Foursquare check-in data and extracts city-specific trajectories.

**Execution Logic**:

1. **Load City Information**: 
   - Reads city coordinates from `dataset_TIST2015_Cities.txt`
   - Creates mapping of city names to coordinates

2. **Load POI Data**:
   - Reads POI information (ID, location, category)
   - For TIST2015: `dataset_TIST2015_POIs.txt`
   - For Gowalla: `gowalla_totalCheckins.txt`

3. **Calculate Distance** (using haversine formula):
   - Computes distance from each POI/check-in to all cities
   - Uses PyTorch for efficient batch computation
   - Assigns each POI to nearest city

4. **Filter by City**:
   - For each city in `EXP_CITIES`, filters relevant check-ins
   - Extracts user, time, venue, location, and category

5. **Output**:
   - Saves city-specific data: `{city_name}_filtered.csv`
   - Columns: `city, user, time, venue_id, utc_time, longitude, latitude, venue_cat_name`

**Key Function**: `haversine_torch()` - Fast distance calculation using PyTorch

**Usage**:
```bash
python -m processing.process_fsq_city_data
```

**Output**: `data/no_address_traj/{city}_filtered.csv`

---

### 3. `process_isp_shanghai.py` - ISP Trajectory Processor

**Purpose**: Processes raw ISP (telecom) trajectory data for Shanghai and matches it with POI categories.

**Execution Logic**:

1. **Load POI Categories**:
   - Function: `load_cat()`
   - Reads `poi.txt` with POI names, locations, and categories
   - Builds KDTree for fast spatial lookup
   - Creates mapping: POI ID → (location, category, name)

2. **Sample Users**:
   - Function: `samples_generator()`
   - Selects top 2000 users by trajectory length
   - Ensures sufficient data quality

3. **Process ISP Data** (dense, frequent check-ins):
   - Function: `load_data_match_cat_telecom()`
   - Parses format: `user_id\ttimestamp,venue_id,lon_lat|...`
   - Matches coordinates to nearest POI using KDTree
   - Groups by day (8am-8pm filter)
   - Optional compression: `dense_session_compress()` removes redundant stops

4. **Process Weibo Data** (sparse, social media check-ins):
   - Function: `load_data_match_sparse_cat()`
   - Similar to ISP but different session definition
   - Groups by 24-hour windows, max 20 points per session

5. **Output**:
   - `Shanghai_filtered.csv`: Dense ISP trajectories
   - `Shanghai_Weibo_filtered.csv`: Sparse Weibo trajectories

**Key Algorithm**: Session compression removes consecutive duplicate locations within 2-hour windows

**Usage**:
```bash
python -m processing.process_isp_shanghai
```

**Output**: `data/no_address_traj/Shanghai*.csv`

---

### 4. `osm_address_deploy.py` - Address Resolution (Deployed Service)

**Purpose**: Enriches trajectory data with OpenStreetMap address information using a self-deployed Nominatim service for large-scale parallel processing.

**Execution Logic**:

1. **Load Venue Coordinates**:
   - Reads all `{city}_filtered.csv` files
   - Extracts unique `(venue_id, longitude, latitude)` tuples

2. **Reverse Geocoding**:
   - Function: `reverse_geocode_v2()`
   - Calls deployed Nominatim server: `http://{server}/reverse`
   - Parameters: lat, lon, zoom=18, language=en-US
   - Returns structured address JSON

3. **Parallel Processing**:
   - Function: `process_map_v2()`
   - Uses `multiprocessing.Pool` with configurable workers
   - Processes multiple venues simultaneously for speed

4. **Output Format**:
   - Saves: `data/nominatim/{city}.csv`
   - Columns: `city, venue_id, Lng, Lat, address`
   - Address is JSON string with structure: `{"road": "...", "suburb": "...", ...}`

**Configuration**:
- `NOMINATIM_DEPLOY_SERVER`: Server IP and port (from environment variable)
- `NOMINATIM_DEPLOY_WORKERS`: Number of parallel workers (default: 10)

**Usage**:
```bash
# Requires deployed Nominatim service
python -m processing.osm_address_deploy
```

**Output**: `data/nominatim/{city}.csv`

---

### 5. `osm_address_web.py` - Address Resolution (Web API)

**Purpose**: Alternative to `osm_address_deploy.py`, uses official Nominatim web API for small-scale testing.

**Execution Logic**:
- Similar to `osm_address_deploy.py` but:
  - Uses `geopy.Nominatim` client
  - Rate-limited (1 request/second)
  - Single-threaded processing
  - Suitable for small datasets or testing

**Differences**:
- **Deploy**: Fast, parallel, requires server setup
- **Web**: Slow, sequential, no setup needed

**Usage**:
```bash
python -m processing.osm_address_web
```

**Output**: `data/nominatim/{city}_address.txt`

---

### 6. `trajectory_address_match.py` - Address Structure Unification

**Purpose**: Converts raw OSM addresses into a standardized 4-level hierarchical structure using LLM parsing.

**Execution Logic**:

1. **Load Raw Addresses**:
   - Reads CSV files from `data/nominatim/`
   - Each row: `city, venue_id, longitude, latitude, address_json`

2. **LLM-based Address Parsing**:
   - Function: `get_response(address)`
   - Sends address string to LLM (configured in `ADDRESS_L4_FORMAT_MODEL`)
   - Prompt: "Extract administrative area, subdistrict, POI name, street name"
   - Returns structured JSON

3. **Parallel Processing**:
   - Class: `Saver` - Thread-safe file writer
   - Uses `ThreadPoolExecutor` for concurrent LLM calls
   - Configurable workers: `ADDRESS_L4_WORKERS`

4. **Address Matching**:
   - Loads trajectory data: `{city}_filtered.csv`
   - Creates key: `{city}_{venue_id}`
   - Matches with parsed address dictionary
   - Adds 4 address columns: `admin, subdistrict, poi, street`

5. **Output Structure**:
   - Intermediate: `data/address_l4/{city}_addr_dict.json`
   - Final: `data/city_data/{city}_filtered.csv`
   - Final columns: `city, user, time, venue_id, utc_time, longitude, latitude, venue_cat_name, admin, subdistrict, poi, street`

**4-Level Address Hierarchy**:
```
Level 1: administrative   (e.g., "Manhattan", "Shibuya Ward")
Level 2: subdistrict      (e.g., "Upper East Side", "neighborhood")
Level 3: poi              (e.g., "Central Park", "Starbucks")
Level 4: street           (e.g., "5th Avenue", "Main Street")
```

**Usage**:
```bash
python -m processing.trajectory_address_match
```

**Output**: `data/city_data/{city}_filtered.csv` (with address columns)

---

### 7. `data.py` - Final Data Preprocessing

**Purpose**: Main data loader and preprocessor for model training. Called automatically by `agent.py`.

**Execution Logic**:

#### Class: `Dataset`

**Initialization Parameters**:
- `dataset_name`: City name (e.g., "nyc", "Shanghai")
- `trajectory_mode`: "user_split" or "trajectory_split"
- `historical_stays`: Number of historical visits (default: 40)
- `context_stays`: Number of context visits (default: 6)
- `traj_min_len`: Minimum trajectory length
- `traj_max_len`: Maximum trajectory length
- `train_sample`: Training data ratio (0.7, 0.5, 0.3, 0.1)
- `test_sample`: Number of test trajectories (default: 200)

#### Main Processing Steps:

**1. Load Dataset** (`get_dataset()`):
- Reads `data/city_data/{city}_filtered.csv`
- Extracts features: time, location, category, address
- Creates datetime features: hour, weekday, AM/PM
- Maps venue IDs to integers
- Averages coordinates for each venue

**2. Compute Trajectories** (`get_trajectories()`):

   **A. Trajectory Splitting** (default mode):
   - Groups check-ins by user
   - Splits into trajectories using 72-hour time windows
   - Assigns unique global trajectory ID (`DL_traj_id`)
   
   **B. Train/Val/Test Split**:
   - **Standard datasets** (NYC, Tokyo):
     - Train: 70% of trajectories
     - Val: 10% of trajectories
     - Test: 20% of trajectories
   - **Shanghai ISP** (WWW2019):
     - Train: 40% of trajectories
     - Val: 10% of trajectories
     - Test: 50% of trajectories
   
   **C. For each test trajectory**:
   - Historical data: All check-ins from training trajectories
   - Context data: All but last check-in from test trajectory
   - Target: Last check-in (prediction target)
   - Ground truth: Actual venue ID and address

**3. Create Test Dictionary**:
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
    'ground_stay': venue_id,
    'ground_pos': [longitude, latitude],
    'ground_addr': [admin, subdistrict, poi, street]
}
```

**4. Generate Baseline Data** (`get_baseline()`):
- For deep learning baselines (STHM, GETNext, SNPM)
- Encodes categorical variables
- Splits into train/val/test CSVs
- Saves to `baselines/{model}/dataset/`

**5. Save Processed Data**:
- `data/processed/test_dictionary_{city}_{mode}.json`
- `data/processed/true_locations_{city}_{mode}.json`
- `data/processed/align_locations_{city}_{mode}.json`

**Key Methods**:
- `get_encode()`: Label encoding for deep learning
- `test_traj_sampling()`: Samples test trajectories
- `train_traj_sampling()`: Samples training trajectories

**Usage**: Called automatically when running:
```bash
python -m agent --city_name=Shanghai ...
```

**Output**: JSON files in `data/processed/`

---

### 8. `convert.py` - Format Converter

**Purpose**: Simple utility to convert tab-separated address files to CSV format.

**Logic**:
- Reads: `data/nominatim/New York_address2.txt` (TSV)
- Converts to: `data/nominatim/New York.csv` (CSV)
- Columns: `city, place_id, lon, lat, address`

**Usage**: Standalone script for format conversion
```bash
python processing/convert.py
```

---

## 📊 Data Flow Diagram

```
Raw Datasets
    ↓
[download.py] → Download datasets
    ↓
Raw Check-in Data
    ↓
[process_fsq_city_data.py] → Extract city trajectories
[process_isp_shanghai.py]  → Process ISP data
    ↓
City Trajectories (no address)
{city}_filtered.csv: city, user, time, venue_id, utc_time, lon, lat, venue_cat_name
    ↓
[osm_address_deploy.py] → Fetch OSM addresses
[osm_address_web.py]
    ↓
Raw Address Data
{city}.csv: city, venue_id, lon, lat, address_json
    ↓
[trajectory_address_match.py] → Parse & structure addresses
    ↓
Enriched Trajectories
{city}_filtered.csv: + admin, subdistrict, poi, street
    ↓
[data.py] → Split & prepare for model
    ↓
Processed Data
test_dictionary_{city}.json
true_locations_{city}.json
```

---

## 🎯 Execution Order

For a complete preprocessing pipeline, execute in this order:

```bash
# 1. Configure cities in config.py
# EXP_CITIES = ["Shanghai", "Tokyo", "NewYork", ...]

# 2. Download raw data
python -m processing.download --data_name=www2019

# 3. Process city-specific trajectories
# For Foursquare datasets:
python -m processing.process_fsq_city_data
# For Shanghai ISP:
python -m processing.process_isp_shanghai

# 4. Fetch addresses from OpenStreetMap
# Requires deployed Nominatim service:
python -m processing.osm_address_deploy
# OR use web API (slower):
python -m processing.osm_address_web

# 5. Match and structure addresses
python -m processing.trajectory_address_match

# 6. Final preprocessing (automatic)
# Called by agent.py when running experiments
python -m agent --city_name=Shanghai ...
```

---

## 🔧 Configuration

Key configuration variables (in `config.py`):

- `EXP_CITIES`: List of cities to process
- `DATASET`: Dataset type ("TIST2015", "gowalla", "www2019")
- `CITY_DATA_DIR`: Output directory for processed data
- `NOMINATIM_PATH`: Directory for address data
- `NOMINATIM_DEPLOY_SERVER`: Address of Nominatim service
- `NOMINATIM_DEPLOY_WORKERS`: Parallel workers for address fetching
- `ADDRESS_L4_FORMAT_MODEL`: LLM model for address parsing
- `ADDRESS_L4_WORKERS`: Parallel workers for LLM calls

---

## 📝 Output Data Schema

### Intermediate Files

**`{city}_filtered.csv` (after step 3)**:
```csv
city,user,time,venue_id,utc_time,longitude,latitude,venue_cat_name
Shanghai,12345,480,venue_001,Tue Apr 03 18:28:06 2016,121.44,31.03,Restaurant
```

**`{city}.csv` (after step 4)**:
```csv
city,venue_id,Lng,Lat,address
Shanghai,venue_001,121.44,31.03,"{\"road\":\"...\",\"suburb\":\"...\"}"
```

**`{city}_filtered.csv` (after step 5, final)**:
```csv
city,user,time,venue_id,utc_time,longitude,latitude,venue_cat_name,admin,subdistrict,poi,street
Shanghai,12345,480,venue_001,Tue Apr 03 18:28:06 2016,121.44,31.03,Restaurant,Pudong,Lujiazui,Grand Hyatt,Century Avenue
```

### Final Processed Files

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

## ⚙️ Dependencies

Key Python packages used:

- `pandas`: Data manipulation
- `numpy`: Numerical operations
- `torch`: GPU-accelerated distance calculations
- `sklearn`: KDTree for spatial queries, train/test split
- `geopy`: Geocoding (web API)
- `requests`: HTTP requests (deployed service)
- `tqdm`: Progress bars
- `json_repair`: Robust JSON parsing
- `multiprocessing`/`ThreadPoolExecutor`: Parallel processing

---

## 🐛 Debugging Tips

1. **Check data paths**: Ensure `config.py` paths match your directory structure
2. **Verify API keys**: Set required keys in `.bashrc` for LLM-based address parsing
3. **Test with small dataset**: Set `EXP_CITIES = ["Tokyo"]` for faster iteration
4. **Monitor memory**: Large cities may require substantial RAM
5. **Check Nominatim service**: Verify `NOMINATIM_DEPLOY_SERVER` is accessible
6. **Inspect intermediate outputs**: Check CSV files after each step

---

## 🔍 Common Issues

**Issue**: "Dataset already present"
- **Solution**: Delete existing files if you want to re-download

**Issue**: Nominatim timeout errors
- **Solution**: Reduce `NOMINATIM_DEPLOY_WORKERS` or increase timeout

**Issue**: LLM parsing failures
- **Solution**: Check API key, network proxy, or LLM availability

**Issue**: Empty trajectories after filtering
- **Solution**: Check `traj_min_len`, `traj_max_len` parameters

---

## 📚 References

- Nominatim Docker: https://github.com/mediagis/nominatim-docker
- OpenStreetMap Nominatim API: https://nominatim.org/
- AgentMove Paper: https://arxiv.org/abs/2408.13986

---

## 📞 Contact

For questions about the processing pipeline, refer to the main README or contact the authors.
