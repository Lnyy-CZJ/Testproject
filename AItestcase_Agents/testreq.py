from requirement_decomposition import run_decomposition

result = run_decomposition(
    source_path="PRD/documents/个人中心需求文档.md",
    config_path="requirement_decomposition.yaml",
)

print("success:", result.success)
print("errors:", result.errors)
print("warnings:", result.warnings)
print("requirements:", len(result.requirements))
print("test_seeds:", len(result.test_seeds))