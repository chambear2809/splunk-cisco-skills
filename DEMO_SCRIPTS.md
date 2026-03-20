# Demo Scripts

Speaker cues are shown in brackets, for example `[pause]` and `[emphasize]`.

## Repeatable Sales Demo Script

Approximate length: 3 to 5 minutes

Use this section as the live, repeatable motion for sales teams. The demo persona is the Splunk admin who has been asked to stand up new Cisco integrations so the business can see the Cisco and Splunk better together story inside Splunk. The key point to establish early is that this repo starts with the product template examples, so product owners can provide the right non-secret details before anyone begins the technical setup.

1. Start with the first-step message.

   "I am the Splunk admin, and I have been asked to stand up new Cisco integrations so the team can see the better together story in Splunk. The first thing I do is not run a setup command. I start with the product template example for the product I want to onboard, and I give that worksheet to the product owner first."

2. Open the relevant `skills/<skill>/template.example`.

   "This template shows exactly what I need to collect up front: hostnames, account names, org IDs, regions, indexes, and feature choices. Instead of chasing information across email and chat, I use a product-specific worksheet that turns a vague request into a clear onboarding plan."

3. Explain how this speeds up getting data into Splunk.

   "Because the product owner sees the required fields immediately, I reduce back-and-forth, avoid missing prerequisites, and accelerate time to value. That matters because the better together story only works when the Cisco telemetry is onboarded, usable, and ready to support decisions."

4. Explain the security boundary.

   "The template is for non-secret values only. I keep secrets in `credentials` or password and token files, which lets me share the intake worksheet without putting sensitive values into git."

5. Show the handoff into execution.

   "Once the worksheet is complete, I keep the local copy as `template.local`, and that becomes the starting point for the skill. From there, the workflow takes me from intake to configured integration to validated data flow."

   "Now the story gets more compelling. Cisco Meraki gives me the cloud-managed network view. Cisco DC Networking gives me the data center view. Cisco Intersight gives me the compute and platform view. Splunk brings those domains together so leaders and operators can see more of the digital footprint in one place and respond with better context."

6. Close with the repeatable value statement.

   "That is the repeatable story I can bring to every product team. I start with the product template example, collect the right details once, onboard faster, and turn Cisco domain data into an executive outcome in Splunk: quicker time to value, broader operational visibility, and a stronger path to digital resilience."

## Video Recording Scripts

### Executive Sales Demo Script

Approximate length: 4 minutes

I am the Splunk admin in this story, and I have been asked to stand up new Cisco integrations so the business can see the better together story in Splunk. [pause]

The point is not just to install three apps. [beat]
The point is to turn Cisco network, data center, and compute telemetry into one operational view in Splunk. [emphasize]

That is what makes this compelling. [beat]
Cisco gives me critical data from across the digital footprint, and Splunk lets me turn that data into visibility, context, and faster decisions. [pause]

The first thing I do when using this repo is start with the product template example for the product I want to onboard. [pause]

Before I run setup, I hand that worksheet to the product owner so they can provide the non-secret details up front. [beat]

Hostnames. Account names. Org IDs. Regions. Indexes. Feature choices. [pause]

That sounds simple, but it is a powerful business step. [beat]
It reduces my usual back-and-forth, removes onboarding friction, and speeds up time to value. [emphasize]

When I try to roll out a Splunk app manually, I know what happens. [pause]

What should be a quick onboarding request turns into a project. [beat]

I find the package. I install it. I configure the environment. I enable the inputs. I restart services. Then I wait to see whether the data actually shows up. [pause]

That is the friction this project removes for me. [emphasize]

Splunk TA Management AI Skills turns that messy, manual process into a guided operating motion for me. [pause]

Instead of relying on tribal knowledge, checklists, and trial and error, I get a repeatable workflow that takes me from intake to validated telemetry. [beat]

And that is why this lands so well in an executive conversation. [pause]

It is not just automation. [beat]
It is a faster, more consistent path from request to usable insight. [emphasize]

For this demo, I am focusing on three Cisco apps that tell a much bigger story. [pause]

Cisco DC Networking gives me the data center view. [beat]
Cisco Meraki gives me the cloud-managed network view. [beat]
Cisco Intersight gives me the compute and platform view. [pause]

Three different operational domains. [beat]
One consistent onboarding experience. [beat]
One better together story inside Splunk. [emphasize]

That is where the business value lands.

I am showing that complex integrations do not have to create operational drag. [pause]
I can move faster without sacrificing consistency. [pause]
And I can shorten the path from install to usable visibility dramatically. [emphasize]

From a buyer's perspective, that matters.

It means faster time to value. [beat]
It means less dependence on a single expert. [beat]
It means more consistency across teams and environments. [beat]
And it means less risk when organizations are trying to move quickly. [pause]

It also changes the conversation. [beat]

The question I am no longer asking is, "Can I get this installed?" [pause]
The question becomes, "How quickly can I turn this data into value?" [emphasize]

That is the real sales story here.

Splunk TA Skills reduces the friction I usually face between being asked for an integration and actually delivering value from it. [pause]

I provide the environment details once. The workflow handles the heavy lifting. Validation confirms the deployment is not just complete, but ready to support real decisions. [beat]

So when I demo Cisco DC Networking, Meraki, and Intersight, I am not just showing three apps. [pause]

I am showing a repeatable operating model. [beat]
A faster path to onboarding. [beat]
And a simpler way to turn Cisco telemetry into outcome-ready Splunk visibility across the environment. [emphasize]

That is the message. [pause]

Less manual effort. [beat]
Faster onboarding. [beat]
More consistency. [beat]
Quicker insight. [pause]

Splunk TA Skills makes my integration work simple, guided, and business-ready, so the better together story becomes visible faster.

### Technical Demo Narration

Approximate length: 4 minutes

I am the Splunk admin in this demo, and I have been asked to stand up new Cisco integrations so I can prove the better together story with real data inside Splunk. [pause]

That means I am not treating Cisco DC Networking, Meraki, and Intersight as isolated installs. [beat]
I am onboarding them as connected sources of context across network, data center, and compute operations, so the organization gets one clearer operating picture. [emphasize]

The first technical step I take in this repo is not the install. [pause]

It is the product template example. [beat]

I start by using the relevant `template.example` as an intake worksheet so the product owner can give me the required non-secret configuration up front. [pause]

That means I know the hostnames, account names, org IDs, regions, indexes, and feature choices before the setup begins. [beat]

It is a small process change, but it removes a lot of deployment friction for me. [emphasize]

What I want to show in this demo is simple. [pause]

I can take integrations that are normally tedious to stand up and turn them into a guided, repeatable workflow. [emphasize]

The technical story is straightforward. [beat]
Standardize intake. [beat]
Onboard consistently. [beat]
Validate outcomes. [pause]

And I am showing that through three Cisco apps. [pause]

First, Cisco DC Networking. [beat]
This is the data center story. I bring in visibility from ACI, Nexus Dashboard, and Nexus 9K through a process that is structured instead of fragile. [pause]

Next, Cisco Meraki. [beat]
This is a strong demo moment because it gives me both breadth and simplicity. I can onboard organization, device, wireless, and security appliance visibility through one guided experience. What is usually repetitive becomes streamlined. [pause]

Then, Cisco Intersight. [beat]
This extends the story into compute and platform operations. Now I am not just talking about networks. I am bringing compute telemetry into Splunk through the same consistent motion. [pause]

And that consistency is the key technical point for me. [emphasize]

The bigger point for me is what happens once all of that Cisco telemetry lands in Splunk. [beat]
Now I can connect more of the digital footprint in one place and move from isolated signals to coordinated visibility. [pause]

No matter which app I am onboarding, the motion feels the same. [beat]
Stand it up. Configure it. Enable data collection. Validate the result. [pause]

That matters because most failed deployments do not fail in obvious ways. [beat]
They fail in the gaps. [pause]

An account gets created, but data collection is incomplete. [beat]
Data starts flowing, but the environment is not aligned for real visibility. [beat]
An install looks successful, but the outcome is still not usable. [pause]

This workflow is designed to help me close those gaps. [emphasize]

It is not just about speed. [beat]
It is about confidence. [pause]

Confidence that I configured the integration correctly. [beat]
Confidence that the right data is flowing. [beat]
Confidence that the telemetry is ready to support real operational decisions. [pause]

That is why this lands well when I demo it. [beat]
I am not asking people to care about setup mechanics for their own sake. [pause]
I am showing a better operating model. [emphasize]

I am showing that Cisco DC Networking, Meraki, and Intersight may bring in very different telemetry, but the onboarding experience feels unified. [pause]

And when the onboarding experience is unified, my team can move faster, standardize more easily, and scale adoption with less effort. [beat]
That is how the better together story becomes operational instead of theoretical. [emphasize]

That is the technical takeaway. [pause]

Different integrations. [beat]
Same guided motion. [beat]
Faster time to usable Splunk visibility across my Cisco environment.

### Troubleshooting Demo Add-On

Approximate length: 2 minutes

This is an optional section you can use when you want to show that the workflow also handles real-world friction, not just the happy path. [pause]

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
But for this demo, I made a deliberate choice to disable SSL verification in the Cisco DC Networking app so the onboarding could continue. [emphasize]

Once I changed that setting, the ACI account was created successfully, the inputs were enabled, Splunk restarted, and data validation passed. [pause]

That is the value of including this section in my demo. [beat]
It shows that the workflow is useful not only when everything is perfect, but also when my environment behaves like a real customer environment. [pause]

So the story is not just that I installed three Cisco integrations. [beat]
The stronger story is that I handled missing configuration details, resolved certificate friction, and still reached working telemetry in a guided, repeatable way. [emphasize]