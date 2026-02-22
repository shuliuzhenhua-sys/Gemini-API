# Gemini 图片 API（官方格式兼容）

本文档说明本项目新增的 HTTP 接口，目标是兼容 Google Gemini 原生 `generateContent` 图片生成请求格式。

## 基本信息

- Base URL：`http://<host>:<port>`
- Method：`POST`
- Path：`/v1beta/models/{model}:generateContent`
- Content-Type：`application/json`
- Header（兼容字段）：`x-goog-api-key: <any-string>`
  - 当前实现中该字段仅用于协议兼容，实际鉴权沿用本项目 Cookie 会话（`SECURE_1PSID` / `SECURE_1PSIDTS` 或本地浏览器 Cookie）。

## 支持的主要请求字段

- `contents[].parts[].text`：提示词文本
- `contents[].parts[].inlineData`：参考图（图生图）
  - `mimeType`：如 `image/png`
  - `data`：base64 图片内容
- `generationConfig.responseModalities`：如 `["IMAGE"]` 或 `["TEXT","IMAGE"]`
- `generationConfig.imageConfig.aspectRatio`：如 `16:9`、`1:1`、`3:4`
- `safetySettings`：可传，当前版本仅透传接收

## 响应结构（核心）

- `candidates[]`
  - `index`
  - `content.role`：`"model"`
  - `content.parts[]`
    - 文本：`{"text":"..."}`
    - 图片：`{"inlineData":{"mimeType":"image/png","data":"<base64>"}}`
  - `finishReason`：`"STOP"`
- `modelVersion`

## 纯文生图示例

```bash
curl -X POST "http://127.0.0.1:8000/v1beta/models/gemini-3.0-flash-thinking:generateContent" \
  -H "Content-Type: application/json" \
  -H "x-goog-api-key: dummy" \
  -d '{
    "contents":[{"parts":[{"text":"Generate a cinematic female portrait, no text, no watermark"}]}],
    "generationConfig":{
      "responseModalities":["IMAGE"],
      "imageConfig":{"aspectRatio":"16:9"}
    }
  }'
```

## 参考图生图示例

```bash
REF_B64=$(base64 -i /path/to/ref.png | tr -d '\n')

curl -X POST "http://127.0.0.1:8000/v1beta/models/gemini-3.0-flash-thinking:generateContent" \
  -H "Content-Type: application/json" \
  -H "x-goog-api-key: dummy" \
  -d "{
    \"contents\":[
      {
        \"parts\":[
          {\"text\":\"基于参考图生成16:9电影感美女写真，光线自然、无文字\"},
          {\"inlineData\":{\"mimeType\":\"image/png\",\"data\":\"$REF_B64\"}}
        ]
      }
    ],
    \"generationConfig\":{
      \"responseModalities\":[\"IMAGE\"],
      \"imageConfig\":{\"aspectRatio\":\"16:9\"}
    }
  }"
```

## 将返回图片保存为文件（示例）

```bash
curl -s -X POST "http://127.0.0.1:8000/v1beta/models/gemini-3.0-flash-thinking:generateContent" \
  -H "Content-Type: application/json" \
  -H "x-goog-api-key: dummy" \
  -d '{
    "contents":[{"parts":[{"text":"Generate a cat icon"}]}],
    "generationConfig":{"responseModalities":["IMAGE"],"imageConfig":{"aspectRatio":"1:1"}}
  }' \
| jq -r '.candidates[0].content.parts[] | select(.inlineData) | .inlineData.data' \
| base64 -d > out.png
```

## 错误码说明（当前实现）

- `400`
  - `Unsupported model: <model>`
  - `Invalid inlineData base64`
  - 未提供文本 part
- `500`
  - Gemini 下游请求失败（Cookie 失效、网络异常、上游错误等）

## 启动

```bash
uv run uvicorn gemini_webapi.api:app --host 0.0.0.0 --port 8000
```

## 实现细节说明

- 默认模型（当调用方不显式指定 model）已切换为：`gemini-3.0-flash-thinking`
- 对于生成图响应，服务端会优先尝试全尺寸链接（`=s2048`）再转为 `inlineData` 返回
- 参考图上传时保留图片扩展名（如 `.png/.jpg`），避免被当作普通文本文件
