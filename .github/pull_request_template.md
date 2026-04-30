## Summary

- 

## Testing

- [ ] `pytest -q`
- [ ] `bats tests/*.bats`
- [ ] `bash -n` for changed shell scripts, or all scripts
- [ ] `shellcheck --severity=warning $(find skills -name '*.sh' -print)`
- [ ] `ruff check skills/ tests/`
- [ ] `yamllint -c .yamllint.yml .github/ skills/splunk-itsi-config/templates skills/splunk-itsi-config/agents`
- [ ] `python3 skills/shared/scripts/generate_deployment_docs.py --check`
- [ ] SCAN catalog check run or intentionally skipped because the local SCAN package is unavailable
- [ ] `python3 tests/check_skill_frontmatter.py`
- [ ] `python3 tests/check_repo_readiness.py`

## Safety

- [ ] I did not commit credentials, tokens, package binaries, rendered output, or `template.local`.
- [ ] New secret-bearing inputs use file-based flags, not direct command-line values.
- [ ] Docs examples do not put secret values in shell history.
