# How the Splunk and Cisco Skills Repo Began

This repository started with a practical goal: make it faster for Cisco engineers to bring Cisco products into Splunk Platform. The first focus was Cisco Technology Add-ons (TAs)—the packages that help Splunk collect, interpret, and work with data from Cisco products. Instead of asking each engineer to rediscover the setup steps, the repo gathered those workflows into reusable skills and scripts.

The idea changed as I began working with AI agents. An agent could do more than point to installation instructions: it could help choose the right workflow, gather the required configuration, prepare a reviewable plan, guide the setup, and check the result. That made the skill itself a useful unit of work. It could combine product knowledge, operating steps, scripts, and validation in one place, while leaving the operator in control of changes.

During this period, I also saw that agents could help solve a larger organizational problem. By extracting Splunk Technology Add-ons and analyzing their files, an agent could identify what data an add-on was designed to bring into Splunk Platform. That visibility helps teams understand the data they are onboarding before deployment and makes planning across engineering and operations much easier.

From there, the repo grew beyond Cisco integrations and beyond installing packages. I began building skills across the Splunk product portfolio: Splunk Enterprise and Splunk Cloud, Observability Cloud, security products, ITSI, SOAR, data onboarding, platform administration, and more. Cisco integrations remained a core part of the library, alongside AppDynamics, ThousandEyes, Galileo, AWS, and other connected technologies.

As the catalog expanded, the purpose became broader: give engineers and operators a consistent way to plan, configure, and validate complex product workflows, whether they work directly from the command line or with an agent in Cursor, Codex, or Claude Code. The skills are designed to make the work repeatable and reviewable. They favor rendering and preflight checks before changes, explicit apply steps, validation afterward, and careful handling of credentials.

The repo is still evolving. Its growth follows the same original motivation: help people connect products and get useful systems working with less guesswork. What began as a way to install Cisco TAs has become a shared library of practical knowledge and automation for the broader Splunk and Cisco ecosystem—and a way to put agent capabilities to work on real operational tasks.
