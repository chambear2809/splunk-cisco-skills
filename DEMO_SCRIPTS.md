# Demo Scripts

Speaker cues are shown in brackets, for example `[pause]` and `[emphasize]`.

## Repeatable Sales Demo Script

Approximate length: 3 to 5 minutes

Use this section as the live, repeatable motion for sales teams. The demo persona is the Splunk admin who has been asked to stand up new Cisco integrations so the business can see the Cisco and Splunk better together story inside Splunk. The key point to establish early is that this is a hosted, downloadable repo a Splunk admin can actually use, not just a one-off lab. It supports Splunk Cloud, Enterprise, and hybrid deployments, and it still starts with product template examples so product owners can provide the right non-secret details before technical setup begins.

1. Start with the repo promise.

   "I am the Splunk admin, and I have been asked to stand up new Cisco integrations so the team can see the better together story in Splunk. What matters first is that this repo is something I can download and use in a real environment. It gives me a repeatable way to install, configure, and validate Cisco integrations instead of improvising each deployment from scratch."

2. Show the environment fit.

   "Before I touch a product, I confirm that the repo supports the environment I actually run. It can work with Splunk Cloud, Splunk Enterprise, and hybrid deployments, so I can start from the operating model that matches my stack instead of forcing a one-size-fits-all install story."

3. Open the relevant `skills/<skill>/template.example`.

   "Once I know it fits my environment, I start with the product template example for the product I want to onboard. This worksheet shows exactly what I need to collect up front: hostnames, account names, org IDs, regions, indexes, and feature choices. Instead of chasing information across email and chat, I use a product-specific worksheet that turns a vague request into a clear onboarding plan."

4. Explain how this speeds up getting data into Splunk.

   "Because the product owner sees the required fields immediately, I reduce back-and-forth, avoid missing prerequisites, and accelerate time to value. That matters because the better together story only works when the Cisco telemetry is onboarded, usable, and ready to support decisions."

5. Explain the security boundary.

   "The template is for non-secret values only. I keep secrets in `credentials` or password and token files, which lets me share the intake worksheet without putting sensitive values into git or chat."

6. Show the handoff into execution.

   "Once the worksheet is complete, I keep the local copy as `template.local`, and that becomes the starting point for the skill. From there, I move through the repo's actual working motion: install the app, run the skill-specific setup, and validate that data is really flowing."

7. Walk through one hero workflow.

   "For a live example, I can start with Cisco Meraki or Cisco Intersight and show a clean end-to-end path from intake to configured inputs to validated telemetry. That gives the audience one concrete success path before I widen the story."

   "Now the story gets more compelling. Cisco Meraki gives me the cloud-managed network view. Cisco DC Networking gives me the data center view. Cisco Intersight gives me the compute and platform view. Splunk brings those domains together so leaders and operators can see more of the digital footprint in one place and respond with better context."

8. Close with the repeatable value statement.

   "That is the repeatable story I can bring to every product team. I start by confirming the deployment model, collect the right details once, keep secrets in the right place, onboard faster, and validate the result. The outcome in Splunk is quicker time to value, broader operational visibility, and a stronger path to digital resilience."

## Video Recording Scripts

### Executive Sales Demo Script

Approximate length: 4 minutes

I am the Splunk admin in this story, and I have been asked to stand up new Cisco integrations so the business can see the better together story in Splunk. [pause]

The first thing that matters to me is that this repo is not just a demo artifact. [beat]
It is a downloadable project I can actually use to install, configure, and validate integrations in a real Splunk environment. [emphasize]

Before I touch a product, I need to know whether it fits the environment I run. [pause]
This repo supports Splunk Cloud, Splunk Enterprise, and hybrid deployments, so I can start from the operating model that matches my stack. [beat]
That matters because real customer environments are not all the same. [pause]

Once I know the repo fits my environment, the first workflow step is the product template example for the product I want to onboard. [pause]

Before I run setup, I hand that worksheet to the product owner so they can provide the non-secret details up front. [beat]

Hostnames. Account names. Org IDs. Regions. Indexes. Feature choices. [pause]

That sounds simple, but it is a powerful business step. [beat]
It reduces my usual back-and-forth, removes onboarding friction, and speeds up time to value. [emphasize]

It also gives me a clean security boundary. [pause]
The worksheet is for non-secret values. [beat]
Secrets stay in local credentials files or password and token files, not in git and not in chat. [emphasize]

From there, the motion is simple and repeatable. [pause]
I install the app. I run the skill-specific setup. I validate that the data is actually flowing. [beat]
That means I am not just showing documentation. I am showing a working operator path from request to usable telemetry. [emphasize]

And that is why this lands so well in an executive conversation. [pause]

It is not just automation. [beat]
It is a faster, more consistent path from request to usable insight. [emphasize]

For a live walkthrough, I can start with one clean hero workflow, like Meraki or Intersight. [pause]
That gives me a concrete example of the repo doing real work before I widen the story. [beat]

Then I expand to the bigger message. [pause]

Cisco DC Networking gives me the data center view. [beat]
Cisco Meraki gives me the cloud-managed network view. [beat]
Cisco Intersight gives me the compute and platform view. [pause]

Three different operational domains. [beat]
One consistent onboarding experience. [beat]
One better together story inside Splunk. [emphasize]

That is where the business value lands.

I am not just showing that I can install three apps. [pause]
I am showing that a Splunk admin can download a repo, fit it to the environment, collect the right details once, handle secrets safely, and move from install to validated visibility faster. [emphasize]

From a buyer's perspective, that matters.

It means faster time to value. [beat]
It means less dependence on tribal knowledge. [beat]
It means more consistency across teams and environments. [beat]
And it means less risk when organizations are trying to move quickly. [pause]

It also changes the conversation. [beat]

The question I am no longer asking is, "Can I get this installed?" [pause]
The question becomes, "How quickly can I turn this data into value?" [emphasize]

That is the real sales story here.

Splunk TA Skills turns onboarding into a repeatable operating motion for the Splunk admin. [pause]
Less manual effort. [beat]
Faster onboarding. [beat]
More consistency. [beat]
Quicker insight. [pause]

That is how the better together story becomes visible faster.

### Technical Demo Narration

Approximate length: 4 minutes

I am the Splunk admin in this demo, and I have been asked to stand up new Cisco integrations so I can prove the better together story with real data inside Splunk. [pause]

The first thing I want to prove is that this repo is something I can actually download and run. [beat]
It is built to support Splunk Cloud, Splunk Enterprise, and hybrid deployments, so I start by matching the workflow to the environment I have. [emphasize]

That matters because the install and setup path is different depending on where the search tier and collection tier live. [pause]

Once I know the target model, I move to the product template example. [beat]

I start by using the relevant `template.example` as an intake worksheet so the product owner can give me the required non-secret configuration up front. [pause]

That means I know the hostnames, account names, org IDs, regions, indexes, and feature choices before the setup begins. [beat]

It is a small process change, but it removes a lot of deployment friction for me. [emphasize]

The security boundary is clear. [pause]

I keep non-secret values in `template.local`. [beat]
I keep Splunk credentials and vendor secrets in local credentials files or password and token files. [pause]
That lets me share the workflow safely without turning the repo into a secret store. [emphasize]

From there, the technical motion follows the same path the README describes. [pause]

Install the app. [beat]
Run the skill-specific setup. [beat]
Validate the deployment and confirm that data is actually arriving. [pause]

For the live walkthrough, I start with one hero path, like Cisco Meraki or Cisco Intersight. [beat]
That lets me show one complete flow from intake to configured account to enabled inputs to validated telemetry. [emphasize]

Then I widen the story across the Cisco portfolio. [pause]

First, Cisco DC Networking. [beat]
This is the data center story. I bring in visibility from ACI, Nexus Dashboard, and Nexus 9K through a process that is structured instead of fragile. [pause]

Next, Cisco Meraki. [beat]
This gives me a cloud-managed network story with broad operational coverage through the same guided motion. What is usually repetitive becomes streamlined. [pause]

Then, Cisco Intersight. [beat]
This extends the story into compute and platform operations. Now I am not just talking about networks. I am bringing compute telemetry into Splunk through the same consistent motion. [pause]

And that consistency is the key technical point for me. [emphasize]

No matter which app I am onboarding, the motion feels the same. [beat]
Confirm the deployment model. [beat]
Standardize intake. [beat]
Install. [beat]
Configure. [beat]
Validate the outcome. [pause]

That matters because most failed deployments do not fail in obvious ways. [beat]
They fail in the gaps. [pause]

An account gets created, but data collection is incomplete. [beat]
Data starts flowing, but the environment is not aligned for real visibility. [beat]
An install looks successful, but the outcome is still not usable. [pause]

This workflow is designed to help me close those gaps. [emphasize]

It is not just about speed. [beat]
It is about confidence. [pause]

Confidence that I matched the right deployment path. [beat]
Confidence that I configured the integration correctly. [beat]
Confidence that the right data is flowing. [beat]
Confidence that the telemetry is ready to support real operational decisions. [pause]

That is why this lands well when I demo it. [beat]
I am not asking people to care about setup mechanics for their own sake. [pause]
I am showing a better operating model for a downloadable Splunk admin toolkit. [emphasize]

Different integrations. [beat]
Same guided motion. [beat]
Faster time to usable Splunk visibility across my Cisco environment.

### Troubleshooting Demo Add-On

Approximate length: 2 minutes

This is an optional branch I use after the main happy-path demo when I want to show that the workflow also handles real-world friction, not just the perfect case. [pause]

It is a realistic Splunk admin moment. [beat]
The better together story does not come from my slides. It comes from getting real Cisco data in, even when the environment is imperfect. [pause]

The first issue I hit was simple, but important. [beat]

When I moved into Cisco DC Networking for ACI, I had the host, username, and password file ready, but I had not included the ACI account name. [pause]

That sounds minor, but it is exactly the kind of small gap that can slow down a real deployment. [beat]

It is also why starting with the product template example matters. [beat]
When that worksheet is complete, small but critical fields are much less likely to be missed. [pause]

The workflow made the missing field obvious right away. [pause]
I was able to supply the ACI account name, use `CVF`, and continue without guesswork. [emphasize]

That is a good demo moment for me because it shows the process is structured. [beat]
It does not just let me rush forward and hope for the best. [pause]
It identifies what is missing, asks me for the right value, and keeps the deployment moving. [emphasize]

The second issue was more realistic from an infrastructure point of view. [beat]

When I tried to create the ACI account, the connection failed because SSL certificate verification blocked the request. [pause]

In other words, I could reach the APIC, but the platform did not trust the certificate presented by that endpoint. [beat]

For a production environment, the better path is to use a trusted certificate chain or the correct CA bundle. [pause]
But for this lab demo, I made a deliberate choice to disable SSL verification in the Cisco DC Networking app so the onboarding could continue. [emphasize]
I make that tradeoff explicit because it is a demo-only workaround, not the recommended production pattern. [pause]

Once I changed that setting, the ACI account was created successfully, the inputs were enabled, Splunk restarted, and data validation passed. [pause]

That is the value of including this section in my demo. [beat]
It shows that the workflow is useful not only when everything is perfect, but also when my environment behaves like a real customer environment. [pause]

So the story is not just that I installed three Cisco integrations. [beat]
The stronger story is that I handled missing configuration details, resolved certificate friction, and still reached working telemetry in a guided, repeatable way. [emphasize]