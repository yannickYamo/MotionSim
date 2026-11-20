# Security

MotionSim runs on your own machine or in your own browser. There is no service of ours to attack and no account.

## Supported version

The latest release, and the live page, which is built from the main branch. A fix goes into a new release; older ones are not patched.

## What it protects

- **The local page.** `motionsim serve` listens on 127.0.0.1 only and answers only requests whose Host and Origin are its own, so another site open in your browser cannot reach it or make it spend your key.
- **Your API key.** Reading a datasheet uses your own key for the model you choose, read from the environment when the local page starts. It is never written to disk, never sent to the page, and leaves your machine only in the call to that model. With a model you host, nothing leaves your machine at all.
- **Files you open.** Device files, setup files, mission profiles and datasheets are data from wherever you got them. They are checked when read; what a setup file holds is reduced to plain values before the page uses it.

A way round any of these is a security fault. So is a file that makes the tool run code, write outside the folder it was told to, or send anything anywhere.

## Reporting a fault

Please report it privately, not in a public issue:

1. **GitHub's private reporting.** On the repository, open the Security tab and choose "Report a vulnerability" ([direct link](https://github.com/yannickYamo/MotionSim/security/advisories/new)). Only the maintainer sees it.
2. **If that form is not offered to you**, open an [issue](https://github.com/yannickYamo/MotionSim/issues/new) titled "Security contact requested" that says only that you have a report, with no details. The maintainer will open a private advisory and add you to it, and the details go there.

Say what you did, what happened, and the version (`motionsim --version`). This is a one-person project: expect an answer within a week or two. You will be credited in the release notes unless you would rather not be.
