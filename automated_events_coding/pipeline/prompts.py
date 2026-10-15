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
* Be sure to include names of relevant people and places. These will be used in downstream processing so it is important that you list these as accurately as possible. 
"""

# Step 2 - Location Extraction
# Input: single Event
# Output: place_names: string[]
STEP2_LOCATION_EXTRACTION = """\
# Location Extraction
## Background
You will be given a description of an event and an article from which that event is drawn. You will need to extract placenames of where the *event* is occuring. Do not just extract placenames from the article. Rather, use it only to inform your context for the event. 
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
"""

# Step 3 - Event-lead Extraction
# Input: Event + Step 2.1 + Step 2.2 outputs
# Output: see schemas.EventLead -- multiday, date, issue_area, scale_of_impact,
# groundwater, infrastructure_involved, jbi_*, non_basin_entity_*
STEP3_EVENT_LEAD = """\
# Event-lead Extraction

<!-- TODO: task instructions -->
# 


## Output Format

```json

```
"""

# Step 4 - (Inter)action Extraction
# Input: single Event
# Output: interactions, actors, summary, type
STEP4_INTERACTION_EXTRACTION = """\
# (Inter)action Extraction

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
