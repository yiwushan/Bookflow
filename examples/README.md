# Examples

## 运行最小离线 pipeline
```bash
python3 scripts/pipeline.py \
  --input examples/sample_book.json \
  --config config/pipeline.json \
  --output examples/sample_output.json
```

## 说明
1. `sample_book.json`：输入样例（含 heading/paragraph/formula/code blocks）。
2. `sample_output.json`：执行后输出（chunk + render_mode + source_anchor）。
