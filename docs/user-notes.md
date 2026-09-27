
## Better Fairness

- Would be nice to frame feedback and submission as tools, more modern and less user-intent confusion

## Boost Cheating

### More Attractive Changes

- Full agent harness that allows code editing
    - More affordances, and more cheating in the paper; realistic
- More realistic task context
    - A repo, CI check, or PR under review. Give higher stakes
- Different model
    - GLM-5.3-Flash, MiMo-V2.6-Flash

### Less Attractive Changes

- Impossible-SWE-bench
    - Most realistic, highest rates, but heavy docker setup
- More attempts (e.g. 10)
    - More like tuning parameter to get from 35% to 40%
    - Models seem to flag human intervention before first attempt
- Reasoning effort (V4 low/high)
    - Also seems like tuning