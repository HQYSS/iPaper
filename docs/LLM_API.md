# iPaper LLM API 调用文档

> 参考文档：
> - [Gemini媒体识别](https://docs.newapi.pro/zh/docs/api/ai-model/chat/gemini/geminirelayv1beta-391536411)
> - [Gemini文本聊天](https://docs.newapi.pro/zh/docs/api/ai-model/chat/gemini/geminirelayv1beta)

---

## 概述

使用第三方 API 代理调用 Gemini 模型，支持：
- **文本聊天**：普通对话
- **媒体识别**：图像、PDF、音频、视频识别
- **流式输出**：SSE 流式响应

---

## API 配置

| 配置项 | 值 |
|--------|-----|
| **Base URL** | `https://api3.xhub.chat/v1` |
| **模型名称** | `gemini-3-pro-preview-thinking` |
| **认证方式** | Bearer Token |
| **流式支持** | ✅ 支持 |

### 价格

| 类型 | 价格 |
|------|------|
| 输入 (Prompt) | $2.00 / 1M tokens |
| 输出 (Completion) | $12.00 / 1M tokens |

---

## 认证方式

使用 Bearer Token 认证：

```
Authorization: Bearer <your-api-key>
```

---

## API 端点

### 基础 URL

```
https://api3.xhub.chat/v1
```

### OpenAI 兼容格式（推荐）

| 功能 | 端点 | 说明 |
|------|------|------|
| 聊天补全 | `POST /chat/completions` | 支持流式 (`stream: true`) |

### Gemini 原生格式

| 功能 | 端点 | 说明 |
|------|------|------|
| 普通生成 | `POST /v1beta/models/{model}:generateContent` | 非流式响应 |
| 流式生成 | `POST /v1beta/models/{model}:streamGenerateContent?alt=sse` | SSE 流式响应 |

### 模型名称

- `gemini-3-pro-preview-thinking`（主要使用）

---

## 请求格式

### 请求头

```http
POST /v1beta/models/gemini-2.5-pro:generateContent HTTP/1.1
Host: api.newapi.pro
Authorization: Bearer sk-xxxxxx
Content-Type: application/json
```

### 请求体结构

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        { "text": "你好，请介绍一下自己" }
      ]
    }
  ],
  "generationConfig": {
    "temperature": 0.7,
    "maxOutputTokens": 8192,
    "topP": 0.95
  },
  "systemInstruction": {
    "parts": [
      { "text": "你是一个专业的学术论文阅读助手。" }
    ]
  },
  "safetySettings": [],
  "tools": []
}
```

### 参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `contents` | array | ✅ | 对话消息列表 |
| `generationConfig` | object | ❌ | 生成配置（温度、最大 token 等） |
| `systemInstruction` | object | ❌ | 系统指令 |
| `safetySettings` | array | ❌ | 安全设置 |
| `tools` | array | ❌ | 工具配置（函数调用等） |

---

## 媒体上传（PDF 识别）

> ⚠️ **重要**：仅支持通过 `inlineData` 以 **base64** 方式上传，不支持 `fileData.fileUri` 或 File API。

### 上传 PDF 示例

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "inlineData": {
            "mimeType": "application/pdf",
            "data": "<base64-encoded-pdf-content>"
          }
        },
        {
          "text": "请总结这篇论文的主要内容"
        }
      ]
    }
  ],
  "generationConfig": {
    "temperature": 0.3,
    "maxOutputTokens": 8192
  }
}
```

### 支持的媒体类型

| 类型 | MIME Type |
|------|-----------|
| PDF | `application/pdf` |
| 图像 | `image/jpeg`, `image/png`, `image/gif`, `image/webp` |
| 音频 | `audio/mp3`, `audio/wav`, `audio/ogg` |
| 视频 | `video/mp4`, `video/webm` |

---

## 响应格式

### 非流式响应

```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          { "text": "这是 AI 的回复内容..." }
        ]
      },
      "finishReason": "STOP",
      "safetyRatings": [
        {
          "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
          "probability": "NEGLIGIBLE"
        }
      ]
    }
  ],
  "usageMetadata": {
    "promptTokenCount": 100,
    "candidatesTokenCount": 500,
    "totalTokenCount": 600
  }
}
```

### 流式响应（SSE）

使用 `?alt=sse` 参数时，响应为 Server-Sent Events 格式：

```
data: {"candidates":[{"content":{"role":"model","parts":[{"text":"这"}]}}]}

data: {"candidates":[{"content":{"role":"model","parts":[{"text":"是"}]}}]}

data: {"candidates":[{"content":{"role":"model","parts":[{"text":"回复"}]}}]}

data: {"candidates":[{"content":{"role":"model","parts":[{"text":""}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":100,"candidatesTokenCount":50,"totalTokenCount":150}}
```

---

## Python 调用示例

### 非流式调用

```python
import httpx
import base64

API_BASE = "https://api.newapi.pro"  # 根据实际配置修改
API_KEY = "sk-xxxxxx"

def chat(messages: list[dict], system_prompt: str = None) -> str:
    """普通文本对话"""
    url = f"{API_BASE}/v1beta/models/gemini-2.5-pro:generateContent"
    
    payload = {
        "contents": messages,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192
        }
    }
    
    if system_prompt:
        payload["systemInstruction"] = {
            "parts": [{"text": system_prompt}]
        }
    
    response = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=60
    )
    response.raise_for_status()
    
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


# 使用示例
messages = [
    {
        "role": "user",
        "parts": [{"text": "你好，介绍一下 Transformer 架构"}]
    }
]
reply = chat(messages, system_prompt="你是一个专业的 AI 研究助手")
print(reply)
```

### 带 PDF 的对话

```python
def chat_with_pdf(pdf_path: str, question: str) -> str:
    """带 PDF 的对话"""
    url = f"{API_BASE}/v1beta/models/gemini-2.5-pro:generateContent"
    
    # 读取 PDF 并转为 base64
    with open(pdf_path, "rb") as f:
        pdf_base64 = base64.b64encode(f.read()).decode("utf-8")
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "application/pdf",
                            "data": pdf_base64
                        }
                    },
                    {
                        "text": question
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 8192
        },
        "systemInstruction": {
            "parts": [{"text": "你是一个专业的学术论文阅读助手。请用中文回答问题。"}]
        }
    }
    
    response = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=120  # PDF 处理可能较慢
    )
    response.raise_for_status()
    
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


# 使用示例
reply = chat_with_pdf("paper.pdf", "这篇论文的主要贡献是什么？")
print(reply)
```

### 流式调用

```python
import httpx
import json

async def chat_stream(messages: list[dict], system_prompt: str = None):
    """流式对话"""
    url = f"{API_BASE}/v1beta/models/gemini-2.5-pro:streamGenerateContent?alt=sse"
    
    payload = {
        "contents": messages,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192
        }
    }
    
    if system_prompt:
        payload["systemInstruction"] = {
            "parts": [{"text": system_prompt}]
        }
    
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            url,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=120
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if "candidates" in data:
                        parts = data["candidates"][0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            yield parts[0]["text"]
```

---

## OpenAI 兼容格式调用（推荐）

由于支持 OpenAI 兼容格式，可以直接使用 `openai` Python SDK，代码更简洁。

### 安装依赖

```bash
pip install openai
```

### 基础调用

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-api-key",  # 从配置读取
    base_url="https://api3.xhub.chat/v1"
)

# 普通对话
response = client.chat.completions.create(
    model="gemini-3-pro-preview-thinking",
    messages=[
        {"role": "system", "content": "你是一个专业的学术论文阅读助手。"},
        {"role": "user", "content": "你好，介绍一下 Transformer 架构"}
    ],
    temperature=0.7,
    max_tokens=8192
)

print(response.choices[0].message.content)
```

### 流式调用

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-api-key",
    base_url="https://api3.xhub.chat/v1"
)

stream = client.chat.completions.create(
    model="gemini-3-pro-preview-thinking",
    messages=[
        {"role": "system", "content": "你是一个专业的学术论文阅读助手。"},
        {"role": "user", "content": "解释一下注意力机制"}
    ],
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### 带 PDF 的对话（OpenAI 格式 + base64 图像）

```python
import base64
from openai import OpenAI

client = OpenAI(
    api_key="your-api-key",
    base_url="https://api3.xhub.chat/v1"
)

def chat_with_pdf(pdf_path: str, question: str) -> str:
    # 读取 PDF 并转为 base64
    with open(pdf_path, "rb") as f:
        pdf_base64 = base64.b64encode(f.read()).decode("utf-8")
    
    response = client.chat.completions.create(
        model="gemini-3-pro-preview-thinking",
        messages=[
            {"role": "system", "content": "你是一个专业的学术论文阅读助手。请用中文回答问题。"},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:application/pdf;base64,{pdf_base64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": question
                    }
                ]
            }
        ],
        max_tokens=8192
    )
    
    return response.choices[0].message.content

# 使用示例
reply = chat_with_pdf("paper.pdf", "这篇论文的主要贡献是什么？")
print(reply)
```

---

## 在 iPaper 中的使用

### 配置文件

在 `~/.ipaper/config.json` 中配置：

```json
{
  "llm": {
    "api_base": "https://api3.xhub.chat/v1",
    "api_key": "",
    "model": "gemini-3-pro-preview-thinking"
  }
}
```

> ⚠️ **API Key 需要用户自行配置**，首次启动时会提示用户输入。

### 对话场景

1. **论文问答**：将 PDF 通过 base64 上传，然后提问
2. **选中文字解释**：将选中文字作为 context 发送
3. **图表解释**：可以截图图表区域，通过 base64 上传

---

## 注意事项

1. **PDF 大小限制**：base64 编码会增加约 33% 的体积，注意 API 的请求大小限制
2. **超时设置**：PDF 处理可能需要较长时间，建议设置 60-120 秒超时
3. **流式响应**：使用 `stream=True` 获取流式响应，提升用户体验
4. **错误处理**：注意处理 rate limit、token limit 等错误
5. **Thinking 模型**：该模型具有思考能力，响应可能较慢但质量更高

