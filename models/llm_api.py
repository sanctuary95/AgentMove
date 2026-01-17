
import os
import random
import httpx
import argparse
from openai import OpenAI

from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
)
from config import PROXY, ATTEMPT_COUNTER, WAIT_TIME_MIN, WAIT_TIME_MAX, VLLM_URL
from utils import token_count


def get_api_key(platform, model_name=None):
    if platform=="OpenAI":
        return os.environ["OpenAI_API_KEY"]
    elif platform=="DeepInfra":
        return os.environ["DeepInfra_API_KEY"]
    elif platform=="vllm":
        return os.environ["vllm_KEY"]
    elif platform=="SiliconFlow":
        return os.environ["SiliconFlow_API_KEY"]
    elif platform=="OpenRouter":
        return os.environ["OpenRouter_API_KEY"]
    elif platform=="TogetherAI":
        return os.environ["TOGETHER_API_KEY"]


class LLMAPI:
    def __init__(self, model_name, platform=None):
        self.model_name = model_name

        # === 2) platform_list å¢žåŠ  TogetherAI ===
        self.platform_list = ["SiliconFlow", "OpenAI", "DeepInfra", 'vllm', "OpenRouter", "TogetherAI"]

        # === 3) model_platforms å¢žåŠ  TogetherAIï¼ˆç¤ºä¾‹ï¼šå…ˆæ”¾ä½ éœ€è¦çš„å‡ ä¸ªçŸ­åï¼‰===
        self.model_platforms = {
            "SiliconFlow":  [],
            "OpenAI":       [],
            "OpenRouter":   [],
            "DeepInfra":    [],
            "vllm":         [],
            "TogetherAI":   [ 'llama3.3-70b-together', 'Qwen 2.5 72B Instruct Turbo', 'DeepSeek-V3.1', 'Llama 3.1 8B Instruct Turbo','DeepSeek-R1-0528','GPT-OSS 20B']  # ä½ å¯ä»¥æŒ‰éœ€å¢žåˆ 
        }

        # === 4) model_mapper å¢žåŠ  TogetherAI æ¨¡åž‹æ˜ å°„ ===
        self.model_mapper = {
                'llama3.3-70b-together': 'meta-llama/Llama-3.3-70B-Instruct-Turbo',
                'Qwen 2.5 72B Instruct Turbo': 'Qwen/Qwen2.5-72B-Instruct-Turbo',
                'DeepSeek-V3.1': 'deepseek-ai/DeepSeek-V3.1',
                'Llama 3.1 8B Instruct Turbo': 'meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo',
                'DeepSeek-R1-0528': 'deepseek-ai/DeepSeek-R1',
                'GPT-OSS 20B': 'openai/gpt-oss-20b'
                
        }
        # Decide platform
        self.platform = None
        
        # å¦‚æžœç”¨æˆ·æ˜¾å¼ä¼ äº† platform ä¸”åˆæ³•ï¼Œå°±ç”¨å®ƒ
        if platform is not None and platform in self.platform_list:
            self.platform = platform
        else:
            # å¦åˆ™æ ¹æ® model_name è‡ªåŠ¨åŒ¹é…
            for p in self.platform_list:
                if self.model_name in self.model_platforms.get(p, []):
                    self.platform = p
                    break
        
        if self.platform is None:
            raise ValueError(f"Invalid API platform:{self.platform} with model:{self.model_name}")
        
        # æ ¡éªŒï¼šæ¨¡åž‹åå¿…é¡»å±žäºŽè¯¥å¹³å°
        if self.model_name not in self.model_platforms[self.platform]:
            support_models = ";".join([";".join(self.model_platforms[k]) for k in self.model_platforms])
            raise ValueError(
                f"Invalid model name {self.model_name}! Please use one of: {support_models} in platform {self.platform}"
            )

        # === 5) client åˆå§‹åŒ–å¢žåŠ  TogetherAI ===
        if self.platform == "OpenAI":
            self.client = OpenAI(
                api_key=get_api_key(platform),
                http_client=httpx.Client(),
            )
        if self.platform == "OpenRouter":
            self.client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=get_api_key(platform),
                http_client=httpx.Client(),
            )
        elif self.platform == "DeepInfra":
            self.client = OpenAI(
                base_url="https://api.deepinfra.com/v1/openai",
                api_key=get_api_key(platform),
                http_client=httpx.Client(),
            )
        elif self.platform == "SiliconFlow":
            self.client = OpenAI(
                base_url="https://api.siliconflow.cn/v1",
                api_key=get_api_key(platform, model_name)
            )
        elif self.platform == 'vllm':
            self.client = OpenAI(
                base_url=VLLM_URL,
                api_key=get_api_key(platform)
            )
        elif self.platform == "TogetherAI":
            self.client = OpenAI(
                base_url="https://api.together.xyz/v1",
                api_key=get_api_key(platform),
                http_client=httpx.Client(),
            )
    
    def get_client(self):
        return self.client
    
    def get_model_name(self):
        return self.model_mapper[self.model_name]
    
    def get_platform_name(self):
        return self.platform

    def get_supported_models(self):
        return self.model_platforms


class LLMWrapper:
    def __init__(self, model_name, platform=None):
        self.model_name = model_name
        self.hyperparams = {
            'temperature': 0.,  # make the LLM basically deterministic
            'max_new_tokens': 100, # not used in OpenAI API
            'max_tokens': 10000,  
            'reasoning_effort': "high",
            'max_input_tokens': 2000 # The maximum number of input tokens
        }
        
        self.llm_api = LLMAPI(self.model_name, platform=platform)
        self.client = self.llm_api.get_client()
        self.api_model_name = self.llm_api.get_model_name()

    @retry(wait=wait_random_exponential(min=WAIT_TIME_MIN, max=WAIT_TIME_MAX), stop=stop_after_attempt(ATTEMPT_COUNTER))
    def get_response(self, prompt_text):
        if "gpt" in self.model_name:
            system_messages = [{"role": "system", "content": "You are a helpful assistant who predicts user next location."}]
        else:
            system_messages = []
        

        if token_count(prompt_text)>self.hyperparams['max_input_tokens']:
            prompt_text = prompt_text[-min(self.hyperparams['max_input_tokens']*3, len(prompt_text)):]
        
        response = self.client.chat.completions.create(
            model=self.api_model_name,
            messages=system_messages + [{"role": "user", "content": prompt_text}],
            max_tokens=self.hyperparams["max_tokens"],
            temperature=self.hyperparams["temperature"]
        )
        full_text = response.choices[0].message.content
        return full_text


if __name__ == "__main__":
    prompt_text = "Who are you?"

    parser = argparse.ArgumentParser()
    parser.add_argument('--model_name', type=str, default="llama3-8b")
    parser.add_argument("--platform", type=str, default="SiliconFlow", choices=["SiliconFlow", "OpenAI", "DeepInfra"])
    args = parser.parse_args()

    llm = LLMWrapper(model_name=args.model_name, platform=args.platform)
    print(llm.get_response(prompt_text))
