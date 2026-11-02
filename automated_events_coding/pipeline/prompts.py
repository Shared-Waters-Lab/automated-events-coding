"""Prompt templates for the LLM-governed pipeline steps.

Fill in the body of each constant below (the task instructions go between the
title and the "Output Format" section). Titles and output schemas are
generated from `pipeline/schemas.py` — regenerate the JSON schema block if the
corresponding model changes.
"""

# Step 1 - Event Extraction
# Input: PR data (text) + Step 0 metadata
# Output: events: Event[]
STEP1_EVENT_EXTRACTION = """\
# Event detection task
## Background
You will be given an article that reports one or more events. We are compiling a data set of current events, so please extract all of the current events. Assume historical events and background information have already been catalogued.
## Definitions
Use the following definition to inform your response:
* Events: These are the current, specific actions taken by actors referenced in the news article, current relative to the writing of the article and the reason why the article is written. The event is singular regardless of the number of riparians and actors involved. Events are comprised of interactions; an event and an interaction are equivalent if there are only two entities interacting. There can be multiple events within a single article; each event should be listed separately. An event is something that has definitively happened and not background information that acts as context for the reader.
* Background: This is information about things that happened in the past that are used to inform the reader of the context of current events. These often include former laws or treaties that have been signed prior to the current events. They also comprise existing infrastructure and other resources like dams, bridges etc....
* Summary: A detailed description of the event as a whole these should be summarized here. It should reflect specific language mentioned in the article, especially key operative verbs.
## Output Format
```json
[
  {
    "event_summary": str // name of event
  },
  // rest of events
]
```
## Notes
* When an action is ambigious use the exact language from the article.
* Pay close attention to what the event really is. To do so be sure to track the verb tenses used. Do not cut up the event into different parts. Instead use your knowledge of news articles to accurately determine each event.
* For each article, try to keep your number of events from 2 to 7, depending of course on the length of the article. 
* Be sure to include names of relevant people and places. This includes relevant geographic information that could help us pin down where is happened, outside of just a country name. These will be used in downstream processing so it is important that you list these as accurately as possible. 
"""

# Step 2 - Location Extraction
# Input: single Event
# Output: place_names: string[]
STEP2_LOCATION_EXTRACTION = """\
# Location Extraction
## Background
You will be given a description of an event and an article from which that event is drawn. You will need to extract placenames of where the *event* is occuring. Do not just extract placenames from the article. Rather, use it only to inform your context for the event. In cases where a given event does not have a country mentioned in it, use the article context to provide the country name for each of non-country placenames.
## Definitions
* Placenames: Only collect placenames that refer to water bodies (including but not limited to rivers, tributaries, dams and other infrastructure and project titles), as well as country, city names. Pay close attention to abbreviations that occur in the article text and event. 
* Please convert demonyms to their country names only when the event is occuring in that country. For example, if you extract "Namibian", convert it first to "Namibia". Otherwise, ignore demonyms entirely. 
* Placename type: Please report whether or not the placename is a country or not, with "country" for the former and "non-country" for the latter.
## Output Format
```json
[
  {
    "placename": str, // placename
    "placename_type": str // either "country" nor "non-country"
  }
]
```
## Notes
* Ensure that you provide at least one country in your response. If it is not directly mentioned in the event, use the rest of the article to determine the relevant country.
"""

# Step 3 - Event-lead Extraction
# Input: Event + Step 2.1 + Step 2.2 outputs
# Output: see schemas.EventLead -- multiday, date, issue_area, scale_of_impact,
# groundwater, infrastructure_involved, jbi_*, non_basin_entity_*
# might need to check proper name groundwater 
STEP3_EVENT_LEAD = """\
# Event-lead Extraction
## Background
You will be given a description of an event and an article from which that event is drawn. You will need to extract key pieces of information about that event and with it populate a structured response.
## Definitions
* Multiday: This is a boolean value which represents whether or not this event happened over multiple days. It will be `false` if the event happens on just a single day. It will be `true` otherwise, including events in which a date range is not explicitly given.  
* Year: This is an string value which represents the year that the event took place in. This is not necessarily the year of the article's publication, but in many cases they will be the same. This is because these articles are about events that happen current to the article's publication. For example, if the article only reports a day of the week or month, then assume that this reference is relative the publication year. Years are expressed as four digits (YYYY). If an event occurs across multiple years, the first date's year should be used. 
* Month: This is an string value which represents the month that the event took place in. This is not the month of the article's publication. Unlike in the case of the year field above, do not assume that this is happening on the same month as the publication month. In cases where the article mentioned relative dates (ex. "yesterday", "last week", "Tuesday"), attempt to determine the month based on the publication month and these markers. Months are expressed as two digits (MM). If an event occurs across multiple months, the first date's month should be used. In instances where the month is unknown, use XX.
* Day: This is an string value which represents the day that the event took place in. This is not the day of the article's publication. Unlike in the case of the year field above, do not assume that this is happening on the same day. In cases where the article mentioned relative dates (ex. "yesterday", "last week", "Tuesday"), attempt to determine the day based on the publication day and these markers. Days are expressed as two digits (DD). If an event occurs across multiple days, the first day's date should be used. In instances where the day is unknown, use XX.
* Groundwater: This is a boolean value which represents whether or not an *event* is about, mentions, or references groundwater. The article may have information about groundwater in it, but if the event is not specifically about groundwater, report `false`. If the event is about, mentions, references groundwater, report `true`. This includes events solely about groundwater as well as both surface and groundwater combined.
* Infrastructure: This is a boolean value which represents whether or not an *event* revolves around or addresses water infrastructure. The article may have information about water infrastructure in it, but if the event does not revolves around water infrastructure, then report `false`. If the event revolves around water infrastructure, report `true`. This does not include tangential mentions of water infrastructure. The water infrastructure must be central to the event. 
* Issue area: Issue area identifies the main topical, content, and/or sectoral issues addressed in the *event*, not the article itself. The issue area covers the topical area that is the focus of the event. More than one issue area can be listed, separated by semi-colon, but not more than three. It is suitable if you only report one issue area if that is the only issue area applicable to the event. Do not feel that you need to add more issue areas. This should not be an exhaustive list of all issues addressed in the *event*, but include the main areas specified. Areas:
  - 0: Not enough information to determine. You are not likely to use this.
  - Water Quality: Main area of focus on water quality concerns, including diverse sources and types of contaminants and pollutants.
  - Water Quantity: Main area of focus is on water quantity, including allocation.  
  - Fisheries: Main area of focus is on fisheries as an economic and/or subsistence activity.  
  - Hydropower: Main area of focus is on hydropower and hydroelectric dams and related facilities.
  - Domestic/Municipal: Main area of focus is on domestic and/or municipal water, which can include urban and rural water supplies and drinking water.
  - Navigation: Main area of focus is on navigation, shipping, and water transportation.  
  - Agriculture: Main area of focus is on agriculture, which can include issues related to both water quality and quantity, such as irrigation, agricultural runoff, and other agricultural uses.  
  - Forestry and Timber: Main area of focus is on forestry and timber as an economic activity. 
  - Infrastructure: Main area of focus is on the planning, development, construction, operation, and/or maintenance of water-related infrastructure.  
  - Climate Change: Main area of focus or area of explicit commitment is on climate change.  
  - Environment: Main area of focus is on environmental issues, this is broadly understood and can include biodiversity, invasive species, fish species and habitat, ecosystem protection, ecosystem restoration, forest protection, erosion, etc.  
  - Flood Management: Main area of focus is on the management of floods or high flow periods. This can include forecasting, warning, preparation, control measures, flood response, and flood relief.  
  - Drought Management: Main area of focus is on the management of drought or low flow/precipitation periods. This can include drought prediction, warning, drought control/mitigation measures, responses, and drought relief.  
  - Socioeconomic Development: Main area of focus is on broader aspects of social and economic development or for the purposes of social and economic development. This can include efforts towards social and economic progress, poverty eradication, industrial development, trade, non-water transportation and telecommunication development, non-hydropower energy, mining, and tourism.  
  - Funding and Financing: Main area of focus is on financial arrangements or issues. Includes both funding and financing arrangements. Funding is defined as monetary support not needing repayment. Financing is defined as monetary support needing repayment.  
  - Territorial and Border Issues: Main area of focus is on the borders and/or territorial issues, including rivers as contiguous borders and territorial area claims within a shared water body (river island) or due to a changing border watercourse (meander).  
* Scale of Impact: This field indicates the scale of the event's impact on adjacent human populations. Note that “impact” is descriptive of what entity/entities are affected and at what levels by the event and its outcome, unrelated to the number of entities involved. This is unlikely to be explicitly be described in the article or event. You will need to extrapolate it from the context of the event and reference the article for more information when needed. Only report one value. Utilizes these codes:
  - Local: Impacts a singular community or individuals. Example: Development funding for clean water wells. 
  - Sub-basin: Impacts one part of a basin. Example: Construction of a dam on a tributary only impacted some of the riparians. 
  - Basin: Impacts the basin as a whole. Example: U.S.-Canada agreements over Great Lakes water quality. 
  - Regional: Impacts on two or more basins in the same region. Example: Electricity grid linkage between the Congo and Nile River basins. 
  - Global: Impacts more than half of the TFDD basins worldwide. Unlikely to be used. Example: Convention on the Protection and Use of Transboundary Watercourses and International Lakes. 
## Output Format

```json
[
  {
    "multiday": bool, // multiday entry
    "year": str, // year of the event
    "month": str, // month of the event
    "day": str, // day of the event
    "groundwater": bool, // groundwater entry
    "infrastructure": bool, // infrastructure entry
    "issue_area": str, // issue area entry
    "scale_of_impact": str, // scale of impact entry
  }
]
```
## Notes
* Be careful of any date preceded by the phrase "Load-Date". This is the date that this article was loaded into the news database from which we took this article. It is very rare that this will be the date that any of the events in the article happen. In almost all cases, you can simply ignore it.
"""

# Step 4.1 - Entity Extraction
# Input: Article, Riparian Countries, Event text
# Output: Entity list
STEP4_1_ENTITY_EXTRACTION = """\
# Entity Extraction Task
## Background
You will be given a news article and an event summary taken from it. You will also be given a list of possible entities which could interact in this event. Based on this information, you will return a list of potential entities who could have interacted in this event.
## Definitions
* Basin entities: These are entities, usually states, which may be riparian to the given basin and who may or may not have interacted with eachother or a non-basin entity in the context of the given event.
* Non-Basin entities: These are entities, usually non-governmetal organizations, multilateral finance or development organization, or non-state entities, which have interacted with eachother or a basin entity in the context of the given event.
* Do not list the following:
  - Names of people, only the organizations and/or states which they represent. 
    - If the person in question is the head of state, president, prime minister or an ambassador, for these purposes, they simply represent the state itself and do not need to be listed as a separate entity.
    - As a result, do not list any entities like "Office of the Prime Minister" or "Office of the President".
    - Do not list regions or provinces mentioned in the event, only the larger entity that they are part of.  
  - Dates or times
  - Quantitative data
  - Concepts
## Output format
```json 
{
  "entity_list":[
    // list potential entities here
  ]
}
```
## Notes
* Recall that you are simply listing *potential* entities in this step. These will be used for downstream processing. We need you need you to be both discerning but also flexible. 
* Ensure that you list them in a flat list in the JSON format above. 
"""

# Step 4.2 - Interaction or Action
# Input: Event text, potential entities per event 
# Output: I, R, M, O, N codes


# Step 4.3 - Interaction Extraction
# Input: Event text, potential entities per event 
# Output: Interaction summary, dyad entity code
STEP4_3_DYAD_EXTRACTION = """\
# Basin-Event Interactions
## Background
You will be given in the text of an event and a set of two entities, which will be either explicitly or implicitly mentioned in the text. You will provide a summary of their, and only their, interactions, as well as a interaction score according the Basins at Risk (BAR) scale, as defined below.
## Definitions
* Interaction summary: A detailed description that explicitly identifies the action/interaction that is coded between the Entities in the BAR Scale. If possible, note the underlying issue or difference of perception between the actors.
* Basins at Risk (BAR) Scale: A numerical score ranging from -7 to +7, with -7 denoting the most negative events, 0 denoting neutral events, and + 7 denoting the most positive events. See the table below describing the "Water Interaction Intensity Scale" for descriptions of the updated BAR Scale categories. 
  - -7: Formal Declaration of War : Water is the trigger/cause of the war declaration (not water as a weapon/casualty).
  - -6: Extensive War Acts: Formal withdrawal of basin treaty (i.e., does not need to be basin wide, butcannot be short-term or over just a single issue); formal withdrawal from an RBO; use of force at large scale (e.g., blowing-up a dam, occupation to control water source/infrastructure, destroy wells); use of water as a weapon (e.g., Israel-Gaza; but only if it meets inclusion criteria of conflict over water).
  - -5: Small Scale Political -Military Hostile Acts: Freezing, suspending, or the abeyance of a basin treaty (i.e., does not need to be basin wide, but cannot be short-term or over just a single issue); freezing, suspending, or the abeyance of participation in an RBO; formal, explicit leaving of a JBI; small-scale violence (e.g., border skirmishes, local transboundary violence).
  - -4: Threats of Force/Taking Economic-Diplomatic Hostile Acts: Pausing/freezing participation in a JBI; taking economic/diplomatic hostile actions (e.g., recalling ambassador, cutting trade ties, cutting access to other resources, such as gas); threatening the use of force (e.g., statements, mobilizing troops); the 'cutting off' of flow of water (i.e., may not 100 percent cut flow, but the verbiage implies hostile intention, e.g., India/Pakistan 2025).
  - -3: Threats of Economic -Diplomatic Hostile Acts : Threatening to take economic/diplomatic hostile actions (e.g., recalling ambassador, cutting trade ties, cutting access to other resources, such as gas); unilateral construction of water projects against another country's protests/opposition; reducing the flow of water to another country (i.e., reduction of flow is secondary and not an intended hostile act by actor, e.g., reducing flow during filling of GERD between Ethiopia-Egypt).
  - -2: Strong Expressions Displaying Hostility in Interaction: Verbal or written expression of political opposition at a high level (e.g., head of state, foreign minister); cancellation of scheduled meetings between officials, visits by ministers, or regularly scheduled or ad hoc political level RBO/JBI meetings.
  - -1: Mild Expressions Displaying Discord in Interaction: Verbal or written expression of opposition/protest at a lower level ( e.g., technical officials , subnational political actors); cancelling of ad hoc meetings between officials, visits by ministers, or regularly scheduled or ad hoc technical level RBO/JBI meetings; media statements of opposition (including social media); failure to reach agreement but intention is still present to come to an agreement.
  - 0: Neutral or non-significant acts for the interstate situation: Rhetorical policy statements; indifference statements; no comment statements (e.g., statements of non -commitment in a conflict/cooperation between other states by a third party or other basin state).
  - +1: Mild Expressions Displaying Interest/Support in Interactions: Verbal or written expressions of support at a lower level (e.g., technical officials, subnational political actors); holding (or agreeing to hold) ad hoc meetings between officials, visits by ministers; media statements of support (including social media).
  - +2: Strong Expressions Displaying Interest/Support in Interactions: Holding, attending, and/or participating in regularly scheduled or ad hoc technical-level RBO/JBI meetings; holding of negotiations/talks or other political level non RBO/JBI meetings; verbal or written expression of political support at a high level (e.g., head of state, foreign minister).
  - +3: Moderate Economic-Political Actions Displaying Interest/Support: Holding, attending, and/or participating in regularly scheduled or ad hoc RBO/JBI Political Level Meetings; financial agreement involving external actors or foreign aid to the basin; joint site visit to infrastructure/projects in the basin; formalized collaboration with non-state actors (e.g., NGOs/CSOs/Private Actors); formal verbal or written expression of apology for action/statement at a high level (e.g., head of state, foreign minister).
  - +4: Strong Economic-Political Actions Displaying Interest/Support: Creation of a joint management plan, basin management plan, etc.; financial agreement between the basin actors; water sale agreements between actors; a singular cooperative action (e.g., releasing flow, starting a joint project, implementing pollution reduction strategy); signing an MOU, declaration, or other non-binding agreement between actors.
  - +5: Minor Water Alliance: Establishing a JBI (Note: If created by a treaty, then code the signing of the treaty and establishing the JBI as two separate events); signing a legally binding single-issue or short-term water treaty (i.e., does not need to be basin wide, but must be short -term or over just a single issue).
  - +6: Major Basin Alliance: Establishing jointly owned water infrastructure through a formal, legally binding arrangement; signing a legally binding formal basin treaty (i.e., does not need to be basin wide, but cannot be short-term or over just a single issu e); establishing an RBO (Note if created by a treaty, then code the signing of the treaty and establishing of the RBO as two separate events).
  - +7: Voluntary Unification into One Nation: Merging voluntarily into one nation (state); forming one nation with one legally binding government because of water. 
## Output format
```json
[
  {
    "interaction_summary": str,
    "dyad_score": str
  }
]
```
"""

# Step 5.1 - Action ID
# Input: actor from Step 4
# Output: entity_name, entity_code
STEP5_1_ACTION_ID = """\
# Action ID

<!-- TODO: task instructions -->

## Output Format

```json
{
  "description": "Step 5.1 output (type == 'action').",
  "properties": {
    "entity_name": {
      "title": "Entity Name",
      "type": "string"
    },
    "entity_code": {
      "title": "Entity Code",
      "type": "string"
    }
  },
  "required": [
    "entity_name",
    "entity_code"
  ],
  "title": "ActionID",
  "type": "object"
}
```
"""

# Step 5.2 - Interaction ID
# Input: actor pair from Step 4
# Output: entity_names, entity_codes, dyad_pairs, dyad_code (per entity), bar_scale
STEP5_2_INTERACTION_ID = """\
# Interaction ID

<!-- TODO: task instructions -->

## Output Format

```json
{
  "$defs": {
    "IRMORole": {
      "description": "Per-entity role in an interaction, aligned index-wise with entity_codes.",
      "enum": [
        "I",
        "R",
        "M",
        "O",
        "N"
      ],
      "title": "IRMORole",
      "type": "string"
    }
  },
  "description": "Step 5.2 output (type == 'interaction').",
  "properties": {
    "entity_names": {
      "items": {
        "type": "string"
      },
      "title": "Entity Names",
      "type": "array"
    },
    "entity_codes": {
      "items": {
        "type": "string"
      },
      "title": "Entity Codes",
      "type": "array"
    },
    "dyad_pairs": {
      "maxItems": 2,
      "minItems": 2,
      "prefixItems": [
        {
          "type": "string"
        },
        {
          "type": "string"
        }
      ],
      "title": "Dyad Pairs",
      "type": "array"
    },
    "irmo_codes": {
      "items": {
        "$ref": "#/$defs/IRMORole"
      },
      "title": "Irmo Codes",
      "type": "array"
    },
    "bar_scale": {
      "title": "Bar Scale",
      "type": "number"
    }
  },
  "required": [
    "entity_names",
    "entity_codes",
    "dyad_pairs",
    "irmo_codes",
    "bar_scale"
  ],
  "title": "InteractionID",
  "type": "object"
}
```
"""
