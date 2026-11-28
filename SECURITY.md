# Security

MotionSim runs on your own machine or in your own browser. There is no service of ours to attack and no account.

## Supported version

The latest release, and the live page, which is built from the main branch. A fix goes into a new release; older ones are not patched.

## What it protects

- **The local page.** `motionsim serve` listens on 127.0.0.1 unless told another address with `--host`, and says so when that address is one other machines can reach. It answers only requests whose Host names this machine (127.0.0.1, localhost or [::1]) and whose Origin, where there is one, is the page itself, so another site open in your browser cannot reach it or make it spend your key. The settings and the local store answer only the page's own requests, as the browser marks them.
- **Your API key.** Reading a datasheet uses your own key for the model you choose: from the environment of the shell that starts the page, or set under Settings on the page, which keeps it in one file, `reader.key` in MotionSim's folder (`~/.motionsim`, or `MOTIONSIM_HOME`). That folder is made readable by you alone and the file by you alone; the file is written whole under a new name and put in place, and a link found where it goes is replaced, never followed. The key is never sent to the page, never put in an answer or a log, and is taken out of whatever a model's service says back before that is shown or logged. It leaves your machine only in the call to that model. With a model you host, nothing leaves your machine at all.
- **Files you open.** Device files, setup files, mission profiles, board files and datasheets are data from wherever you got them. They are checked when read and held to a size, a depth and a count of what they hold; a file outside those is refused in words, within seconds and a bounded amount of memory. An archive is listed and never unpacked; an XML file that declares a document type or an entity is refused; what a setup file holds is reduced to plain values before the page uses it.
- **The service itself.** Each kind of request is held to its own size and refused unread past it, a connection that stops sending is dropped after 30 seconds, and the app runs only a few searches at once. A search whose page has gone stops before its next step.
- **The container.** `docker-compose.yml` publishes the page on 127.0.0.1 only, runs it as a user who is not root, with no capabilities, a read-only file system, and bounds on memory and processes; it writes only to its volume. The key is not passed in from the shell unless you say so in that file.

A way round any of these is a security fault. So is a file that makes the tool run code, write outside the folder it was told to, or send anything anywhere.

## Reporting a fault

Please report it privately, not in a public issue:

1. **GitHub's private reporting.** On the repository, open the Security tab and choose "Report a vulnerability" ([direct link](https://github.com/yannickYamo/MotionSim/security/advisories/new)). Only the maintainer sees it.
2. **If that form is not offered to you**, open an [issue](https://github.com/yannickYamo/MotionSim/issues/new) titled "Security contact requested" that says only that you have a report, with no details. The maintainer will open a private advisory and add you to it, and the details go there.

Say what you did, what happened, and the version (`motionsim --version`). This is a one-person project: expect an answer within a week or two. You will be credited in the release notes unless you would rather not be.
