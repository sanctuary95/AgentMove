# -*- coding: latin-1 -*-

import os
import json
import time
import tqdm
import random
import argparse
import multiprocessing
from datetime import datetime
import asyncio

from models.prompts import prompt_generator_agent
from processing.data import Dataset
from models.llm_api import LLMWrapper
from models.world_model import SpatialWorld, SocialWorld
from models.personal_memory import Memory
from models.prompts import prompt_generator
from utils import create_dir, extract_json, haversine_distance
from config import PROXY, PROCESSED_DIR
from run_llm_with_poi_mcp import _fetch_pois_via_mcp  # Importing the POI fetch logic

random.seed(100)


def _append_jsonl(path: str, record: dict) -> None:
    """Append one JSON record per line."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class Agent:
    def __init__(
        self,
        city_name,
        platform,
        model_name,
        spatial_world: SpatialWorld,
        social_world: SocialWorld,
        memory_unit: Memory,
        prompt_type,
        save_dir,
        use_int_venue,
        social_info_type,
    ):
        self.city_name = city_name
        self.platform = platform
        self.model_name = model_name

        self.llm_model = LLMWrapper(model_name, platform)
        self.spatial_world = spatial_world
        self.social_world = social_world
        self.memory_unit = memory_unit

        self.prompt_type = prompt_type
        self.save_dir = save_dir
        self.use_int_venue = use_int_venue
        self.social_info_type = social_info_type
        self.stay_points = None  # Placeholder for stay points data, if needed elsewhere

    async def get_nearby_pois(self, prev_lat: float, prev_lon: float, repo_root: str) -> dict:
        """
        Fetch nearby POIs based on the given latitude and longitude.
        """
        try:
            pois = await _fetch_pois_via_mcp(
                repo_root=repo_root,
                lat=prev_lat,
                lon=prev_lon,
                radius_m=800,  # Default radius in meters
                poi_keys=None,
                name_query=None,
                limit=60,  # Limit number of POIs
                timeout_overpass_s=60,
                split_by_key=True,
                compact=True,
                include_tags=False,
            )
            return pois
        except Exception as e:
            print(f"Failed to fetch POIs: {e}")
            return {}

    def predict(self, user_id, traj_id, traj_seqs, target_stay, true_value, stay_points=None):
        """
        Predict the next POI based on trajectory sequences, fetched POIs, and stay points.
        Returns:
            dict: predictions dict with keys: input/output/prediction (+ optional metadata)
        """
        if stay_points is None:
            stay_points = self.stay_points  # Use instance-level stay_points by default

        # Spatial world model info
        spatial_world_info = self.spatial_world.get_world_info()

        # Personal memory
        memory_info = self.memory_unit.read_memory(user_id, target_stay)

        # Social world model
        last_venue_id = traj_seqs["context_stays"][-1][3]
        self_history_points = [x[3] for x in traj_seqs["context_stays"]]
        social_world_info = self.social_world.get_world_info(
            last_venue_id, self_history_points, self.social_info_type
        )

        # Previous check-in point coordinates
        prev_lat = traj_seqs["context_pos"][-1][1]
        prev_lon = traj_seqs["context_pos"][-1][0]
        repo_root = os.path.abspath(os.getcwd())

        # Fetch nearby POIs asynchronously
        poi_info = asyncio.run(self.get_nearby_pois(prev_lat, prev_lon, repo_root))

        # Final prompt: add nearby POI info to the prompt
        prompt_text = prompt_generator_agent(
            traj_seqs,
            self.prompt_type,
            spatial_world_info,
            memory_info,
            social_world_info,
            poi_info,
        )

        pre_text = self.llm_model.get_response(prompt_text=prompt_text)

        # Prediction results extraction
        # 先尝试 prediction，再兜底 recommendation（因为你原始代码是 recommendation）
        output_json, prediction, reason = extract_json(pre_text, prediction_key="prediction")
        if not prediction:
            output_json, prediction, reason = extract_json(pre_text, prediction_key="recommendation")

        predictions = {
            "input": prompt_text,
            "output": output_json,
            "prediction": prediction,
        }
        return predictions

    def get_predictions(self):
        raise NotImplementedError(
            "Define how predictions are generated for each user and trajectory."
        )


class Agents:
    def __init__(
        self,
        platform,
        model_name,
        prompt_type,
        city_name,
        prompt_num,
        use_int_venue,
        dataset: Dataset,
        workers=1,
        exp_name="",
        traj_min_len=3,
        traj_max_len=100,
        sample_one_traj_of_user=False,
        social_world: SocialWorld = None,
        social_info_type="address",
        memory_lens=15,
        skip_existing_is_on=False,
        max_explore_places=5,
        max_sample_trajectories=1,
    ):
        self.city_name = city_name
        self.platform = platform
        self.model_name = model_name
        self.prompt_type = prompt_type
        self.prompt_num = prompt_num
        self.exp_name = exp_name
        self.traj_min_len = traj_min_len
        self.traj_max_len = traj_max_len
        self.sample_one_traj_of_user = sample_one_traj_of_user
        self.social_world = social_world
        self.social_info_type = social_info_type
        self.memory_lens = memory_lens
        self.skip_existing_is_on = skip_existing_is_on
        self.max_explore_places = max_explore_places
        self.max_sample_trajectories = max_sample_trajectories

        # test_dictionary, true_locations
        test_dataset, self.ground_data = dataset.get_generated_datasets()
        self.trajectories = []
        self.trajectory_groups = []
        self.known_stays = {}
        self.use_int_venue = use_int_venue
        self.workers = workers
        self.save_dir = os.path.join(
            "results/", self.exp_name, self.city_name, "agentmove/", self.model_name, self.prompt_type
        )
        create_dir(self.save_dir)

        self.trajs_sampling(test_dataset)

        # 输出路径：每条预测一行 JSON
        self.outputs_jsonl_path = os.path.join("outputs", "predictions.jsonl")

    def trajs_sampling(self, test_dataset):
        counter = 0
        user_list = [str(y) for y in sorted([int(x) for x in list(test_dataset.keys())])]
        for user_id in user_list:
            v = test_dataset[user_id]
            traj_ids = [str(y) for y in sorted([int(x) for x in list(v.keys())])]

            if self.city_name in ["Shanghai"]:
                if len(traj_ids) == 0:
                    continue
            else:
                if len(traj_ids) < self.traj_min_len:
                    continue
                if len(traj_ids) > self.traj_max_len:
                    continue

            traj_list = []
            traj_count = 0
            for traj_id in traj_ids:
                self.trajectories.append((user_id, traj_id, v[traj_id]))
                traj_list.append((user_id, traj_id, v[traj_id]))

                counter += 1
                traj_count += 1
                if self.sample_one_traj_of_user:
                    break
                else:
                    if traj_count > self.max_sample_trajectories:
                        break

            self.trajectory_groups.append(tuple(traj_list))
            self.known_stays[user_id] = v[traj_ids[0]]["historical_stays_long"]

            if counter >= self.prompt_num:
                print(
                    "Data is prepared, Except:{} Real:{} Users:{}".format(
                        self.prompt_num, counter, len(self.trajectory_groups)
                    )
                )
                break
        if counter < self.prompt_num:
            print(
                "Data is not enough, Except:{} Real:{} Users:{}".format(
                    self.prompt_num, counter, len(self.trajectory_groups)
                )
            )

    def skip_existing_file(self, user_id, traj_id):
        filename = f"{self.model_name}_{self.prompt_type}_{user_id}_{traj_id}_{self.use_int_venue}.json"
        file_path = os.path.join(self.save_dir, filename)
        return os.path.exists(file_path)

    def get_predictions(self):
        stay_points = {}
        if self.prompt_type == "llmmove":
            for traj in tqdm.tqdm(self.trajectories):
                for idx, point in enumerate(traj[2]["historical_stays"]):
                    stay_points[int(point[3])] = {
                        "poi": int(point[3]),
                        "cat": point[2],
                        "pos": traj[2]["historical_pos"][idx],
                    }
                for idx, point in enumerate(traj[2]["context_stays"]):
                    stay_points[int(point[3])] = {
                        "poi": int(point[3]),
                        "cat": point[2],
                        "pos": traj[2]["context_pos"][idx],
                    }
                for user, trajs in self.ground_data.items():
                    for traj_id, info in trajs.items():
                        if int(info["ground_stay"]) not in stay_points:
                            stay_points[int(info["ground_stay"])] = {
                                "poi": int(info["ground_stay"]),
                                "cat": None,
                                "pos": info["ground_pos"],
                            }

        if self.workers == 1:
            for traj in tqdm.tqdm(self.trajectories):
                user_id, cur_context_stays = self.single_prediction(traj, stay_points, None)
                self.known_stays[user_id].extend(cur_context_stays)
        elif args.sample_one_traj_of_user:
            with multiprocessing.Pool(self.workers) as pool:
                _ = pool.starmap(
                    self.single_prediction, [(traj, stay_points, None) for traj in self.trajectories]
                )
        else:
            raise NotImplementedError(
                "Multiprocessing is not implemented yet, please use single process for now."
            )

    def single_prediction_group(self, trajs, shared_dict):
        for traj in trajs:
            user_id, cur_context_stays = self.single_prediction(traj, shared_dict)
            with shared_dict["lock"]:
                shared_dict["counter"][0] += 1
                shared_dict["data"][user_id].extend(cur_context_stays)

    def single_prediction(self, traj, stay_points, shared_dict=None):
        user_id, traj_id, traj_seqs = traj

        if self.skip_existing_is_on and self.skip_existing_file(user_id=user_id, traj_id=traj_id):
            return (user_id, traj_seqs.get("context_stays", []))

        # spatial world model
        spaital_world = SpatialWorld(
            model_name=self.model_name,
            platform=self.platform,
            city_name=self.city_name,
            traj_seqs=traj_seqs,
            explore_num=self.max_explore_places,
        )

        # personal memory
        cur_context_stays = traj_seqs.get("context_stays", [])
        target_stay = traj_seqs.get("target_stay", [])

        if self.workers == 1 or self.sample_one_traj_of_user:
            cur_know_stays = self.known_stays[user_id]
        else:
            with shared_dict["lock"]:
                cur_know_stays = shared_dict["data"][user_id]

        memory_unit = Memory(
            know_stays=cur_know_stays,
            context_stays=cur_context_stays,
            memory_lens=self.memory_lens,
        )

        # agent
        agent = Agent(
            city_name=self.city_name,
            platform=self.platform,
            model_name=self.model_name,
            spatial_world=spaital_world,
            social_world=self.social_world,
            memory_unit=memory_unit,
            prompt_type=self.prompt_type,
            save_dir=self.save_dir,
            use_int_venue=self.use_int_venue,
            social_info_type=self.social_info_type,
        )

        # predict
        true_value = self.ground_data[user_id][traj_id]
        pred = agent.predict(user_id, traj_id, traj_seqs, target_stay, true_value, stay_points)

        # 组装输出：next check-in = predicted next POI id (top1)
        prev_lat = traj_seqs["context_pos"][-1][1]
        prev_lon = traj_seqs["context_pos"][-1][0]

        prediction_list = pred.get("prediction", None)

        top1 = None
        topk = None
        if isinstance(prediction_list, list) and len(prediction_list) > 0:
            topk = prediction_list
            top1 = prediction_list[0]
        else:
            # 解析失败时，可能是 str / None；也落盘便于 debug
            topk = prediction_list
            top1 = None

        record = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "city_name": self.city_name,
            "exp_name": self.exp_name,
            "platform": self.platform,
            "model_name": self.model_name,
            "prompt_type": self.prompt_type,
            "user_id": user_id,
            "traj_id": traj_id,
            "prev_checkin": {"lat": prev_lat, "lon": prev_lon},
            "true_next_poi": true_value.get("ground_stay"),
            "predicted_next_poi": top1,
            "predicted_topk_pois": topk,
            "llm_output_json": pred.get("output"),
        }

        _append_jsonl(self.outputs_jsonl_path, record)

        return (user_id, cur_context_stays)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city_name", type=str, default="Shanghai")
    parser.add_argument("--model_name", type=str, default="qwen2.5-7b")
    parser.add_argument(
        "--platform",
        type=str,
        default="SiliconFlow",
        choices=["SiliconFlow", "OpenAI", "DeepInfra", "vllm", "OpenRouter", "TogetherAI"],
    )
    parser.add_argument("--trajectory_mode", type=str, default="trajectory_split", choices=["trajectory_split"])
    parser.add_argument("--historical_stays", type=int, default=15)
    parser.add_argument("--context_stays", type=int, default=6)
    parser.add_argument("--traj_min_len", type=int, default=3)
    parser.add_argument("--traj_max_len", type=int, default=10)
    parser.add_argument("--prompt_num", type=int, default=5)
    parser.add_argument("--sample_one_traj_of_user", action="store_true")
    parser.add_argument("--max_sample_trajectories", type=int, default=100)
    parser.add_argument("--use_int_venue", action="store_true", help="Use int Venue ID")
    parser.add_argument(
        "--prompt_type",
        type=str,
        default="agent_move_v6",
        choices=["agent_move_v6", "origin", "llmmob", "llmzs", "llmmove"],
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--exp_name", type=str, default="")
    parser.add_argument("--social_info_type", type=str, default="address")
    parser.add_argument("--memory_lens", type=int, default=15)
    parser.add_argument("--skip_existing_prediction", action="store_true")
    parser.add_argument("--max_neighbors", type=int, default=10)
    parser.add_argument("--max_explore_places", type=int, default=5)

    args = parser.parse_args()
    print("INFO START TIME:{}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("args:{}".format(args.__dict__))

    print(
        "runnning experiment in city@{} model@{} samples:{} type:{}".format(
            args.city_name, args.model_name, args.prompt_num, args.prompt_type
        )
    )
    start_time = time.time()

    dataset = Dataset(
        dataset_name=args.city_name,
        traj_min_len=2 if args.city_name in ["Shanghai"] else 3,
        trajectory_mode=args.trajectory_mode,
        historical_stays=args.historical_stays,
        context_stays=args.context_stays,
        save_dir=PROCESSED_DIR,
        use_int_venue=args.use_int_venue,
    )

    social_world = SocialWorld(
        traj_dataset=dataset,
        save_dir=PROCESSED_DIR,
        city_name=args.city_name,
        khop=1,
        max_neighbors=args.max_neighbors,
    )

    agents = Agents(
        city_name=args.city_name,
        platform=args.platform,
        model_name=args.model_name,
        prompt_type=args.prompt_type,
        prompt_num=args.prompt_num,
        use_int_venue=args.use_int_venue,
        dataset=dataset,
        workers=args.workers,
        exp_name=args.exp_name,
        traj_max_len=args.traj_max_len,
        traj_min_len=args.traj_min_len,
        sample_one_traj_of_user=args.sample_one_traj_of_user,
        social_world=social_world,
        social_info_type=args.social_info_type,
        memory_lens=args.memory_lens,
        skip_existing_is_on=args.skip_existing_prediction,
        max_explore_places=args.max_explore_places,
        max_sample_trajectories=args.max_sample_trajectories,
    )

    agents.get_predictions()
    print("runnning experiment within {} seconds".format(int(time.time() - start_time)))
