# Recommended `main` branch protection

Branch protection is a GitHub repository setting, not a file that GitHub Desktop can enable locally. After the CI workflow has run once, configure `main` in GitHub's repository settings with:

- Require a pull request before merging.
- Require at least one approving review.
- Dismiss stale approvals when new commits are pushed.
- Require status checks to pass before merging.
- Select these required checks:
  - `Repository hygiene`
  - `Regime Trading focused checks`
  - `Swing checks`
  - `Pattern Trading checks`
  - `Intraday static checks`
- Require branches to be up to date before merging.
- Block force pushes and branch deletion.

Keep direct pushes to `main` available only as an explicit owner decision while the repository is being stabilized. Do not enable an irreversible ruleset until the first CI run has confirmed the exact check names.
