# dataset

Daily sync of the [API Price Index](https://apipriceindex.com) dataset to
[Hugging Face Datasets](https://huggingface.co/datasets/apipriceindex/llm-api-prices).

A scheduled GitHub Action pulls `all.json` + `pricing-history.csv` from the
live index every day at 07:30 UTC, flattens the models into `models.csv`,
and pushes the snapshot. If the index is unreachable or looks wrong, nothing
is pushed — the previous snapshot stays up.

Prefer the live endpoints — always fresher than any snapshot:

- <https://apipriceindex.com/api/all.json>
- <https://apipriceindex.com/openapi.json>
- MCP server: `pip install apipriceindex-mcp`

## License

Code: MIT. Data: [CC BY 4.0](https://apipriceindex.com/use-this-data/),
attribution "API Price Index".
