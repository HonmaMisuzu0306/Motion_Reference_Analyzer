def recommendations():
    return [
        dict(
            id=f"qwen3-vl:{size}b",
            profile=profile,
            use="画面、运动和排版语义分析",
            official_url=f"https://ollama.com/library/qwen3-vl:{size}b",
            artifact_size_bytes=bytes_,
            validation_status="已有本项目真实验收" if size == 4 else "候选，尚未本项目验收",
            resource_note="文件大小不等于运行内存/显存需求；多帧输入还需额外资源",
            checked_at="2026-10-02",
        )
        for size, profile, bytes_ in [
            (2, "轻量配置", 1900000000),
            (4, "均衡配置", 3300000000),
            (8, "较充裕内存/显存", 6100000000),
        ]
    ] + [
        dict(
            id="PP-OCRv5",
            profile="文字识别（CPU可用）",
            use="中/日/英文字检测和识别",
            official_url="https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html",
            artifact_size_bytes=None,
            validation_status="英文样本已验收，日文待验收",
            resource_note="按语言下载检测及识别推理模型，解压后配置本地目录",
            checked_at="2026-10-02",
        )
    ]
