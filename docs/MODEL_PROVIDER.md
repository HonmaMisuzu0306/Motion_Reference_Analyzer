# Model Provider

## VisionProvider 接口

```python
class VisionProvider:
    def analyze_images(self, images, prompt):
        ...

    def get_model_info(self):
        ...
```

## 优先测试模型

- Qwen3-VL 2B
- Qwen3-VL 4B
- Qwen3-VL 8B

## 未来扩展

- Ollama
- llama.cpp
- OpenAI-compatible local endpoint
- LM Studio
- vLLM
