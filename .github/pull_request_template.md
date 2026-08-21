## Summary

-

## Testing

- [ ] Agent Skills specification/best-practice impact reviewed: https://agentskills.io/specification
- [ ] `pre-commit run --all-files`
- [ ] `pytest -q`
- [ ] `bats tests/*.bats`
- [ ] `bash -n` for changed shell scripts, or all scripts
- [ ] `shellcheck --severity=warning $(find agent skills scripts -name '*.sh' -print)`
- [ ] Pinned SCAN source fixture and generated catalog freshness check passes

## Safety

- [ ] I did not commit credentials, tokens, package binaries, rendered output, or `template.local`.
- [ ] New secret-bearing inputs use file-based flags, not direct command-line values.
- [ ] Docs examples do not put secret values in shell history.
