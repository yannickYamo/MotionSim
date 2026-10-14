# Security

MotionSim runs on your own machine or in your own browser. There is no service of ours to attack and no account.

What it does handle that is worth protecting:

- **Your API key.** Reading a datasheet uses your own Anthropic API key, read from the environment when the local page starts. It is never written to disk, never sent to the page, and leaves your machine only in the call to Anthropic.
- **The local page.** `motionsim serve` listens on 127.0.0.1 only and answers only requests whose Host and Origin are its own, so another site open in your browser cannot make it spend your key.
- **Files you open.** Device files, setup files and mission profiles are data from wherever you got them. They are checked when read; what a setup file holds is reduced to plain values before the page uses it.

If you find a way round any of these, please report it privately through the repository's security advisories on GitHub ("Report a vulnerability" under the Security tab), not in a public issue. Say what you did and what happened. This is a one-person project: expect an answer within a week or two.
