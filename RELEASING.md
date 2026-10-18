# Releasing Tomville to PyPI

Releases are built and uploaded by GitHub Actions (`.github/workflows/release.yml`) with PyPI **trusted publishing**: no password or token is stored anywhere.

## One-time setup (Tom, on the websites)

1. **PyPI account** with two-factor authentication: <https://pypi.org/account/register/>
2. **Add a pending trusted publisher** for the new project: <https://pypi.org/manage/account/publishing/>
   - PyPI Project Name: `tomville`
   - Owner: `DuongAnh1201`
   - Repository name: `tomville`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. **Same on TestPyPI** (for dry runs), with its own account: <https://test.pypi.org/manage/account/publishing/>, environment name `testpypi`.
4. **GitHub environments**: repo → Settings → Environments → create `pypi` and `testpypi`. For `pypi`, add yourself under "Required reviewers" so every real upload waits for your click.

## Dry run on TestPyPI

Actions → Release → Run workflow (on `main`). It runs the tests, builds, installs the wheel, and uploads to TestPyPI. Then, on any machine:

```bash
uv tool install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ tomville
tmv --version
```

TestPyPI never accepts the same version twice; bump the version (`uv version --bump patch`) if you need another dry run.

## A release

1. On a branch: set the version (`uv version 0.1.0`), note it under **Changes** in `milestones.md`, PR, merge.
2. Tag `main` and push the tag:
   ```bash
   git switch main && git pull
   git tag v0.1.0 && git push origin v0.1.0
   ```
3. The workflow checks that the tag matches `pyproject.toml`, runs the tests, builds, installs and runs the wheel, then waits for your approval in the `pypi` environment and uploads.
4. Check: <https://pypi.org/project/tomville/> and `uv tool install tomville`.

A version on PyPI can never be replaced, only yanked. If something is wrong, fix it and release the next patch version.
