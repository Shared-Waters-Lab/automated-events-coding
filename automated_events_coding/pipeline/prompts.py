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
* Pay close attention to what the event really is. To do so be sure to track the verb tenses used.
"""

# Step 2 - Location Extraction
# Input: single Event
# Output: place_names: string[]
STEP2_LOCATION_EXTRACTION = """\
# Location Extraction

<!-- TODO: task instructions -->

## Output Format

```json
{
  "description": "Step 2 output.",
  "properties": {
    "place_names": {
      "items": {
        "type": "string"
      },
      "title": "Place Names",
      "type": "array"
    },
    "gw_mentioned": {
      "title": "Gw Mentioned",
      "type": "boolean"
    }
  },
  "required": [
    "place_names",
    "gw_mentioned"
  ],
  "title": "PlaceNames",
  "type": "object"
}
```
"""

# Step 3 - Event-lead Extraction
# Input: Event + Step 2.1 + Step 2.2 outputs
# Output: see schemas.EventLead -- multiday, date, issue_area, scale_of_impact,
# groundwater, infrastructure_involved, jbi_*, non_basin_entity_*
STEP3_EVENT_LEAD = """\
# Event-lead Extraction

<!-- TODO: task instructions -->

## Output Format

```json
{
  "$defs": {
    "EventDate": {
      "properties": {
        "day": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Day"
        },
        "month": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Month"
        },
        "year": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Year"
        }
      },
      "title": "EventDate",
      "type": "object"
    },
    "IssueArea": {
      "description": "Controlled vocabulary from the codebook; an event may have several.",
      "enum": [
        "0",
        "Water Quality",
        "Water Quantity",
        "Fisheries",
        "Hydropower",
        "Domestic/Municipal Water",
        "Navigation",
        "Agriculture",
        "Forestry and Timber",
        "Infrastructure",
        "Climate Change",
        "Environment",
        "Flood Management",
        "Drought Management",
        "Socioeconomic Development",
        "Funding and Financing",
        "Territorial and Border Issues"
      ],
      "title": "IssueArea",
      "type": "string"
    },
    "ScaleOfImpact": {
      "description": "Codebook's \\"Scale Of Impact\\" -- descriptive of who's affected, not headcount.",
      "enum": [
        0,
        1,
        2,
        3,
        4,
        99
      ],
      "title": "ScaleOfImpact",
      "type": "integer"
    }
  },
  "description": "Step 3 output.",
  "properties": {
    "multiday": {
      "title": "Multiday",
      "type": "boolean"
    },
    "date": {
      "$ref": "#/$defs/EventDate"
    },
    "issue_area": {
      "items": {
        "$ref": "#/$defs/IssueArea"
      },
      "title": "Issue Area",
      "type": "array"
    },
    "scale_of_impact": {
      "$ref": "#/$defs/ScaleOfImpact"
    },
    "groundwater": {
      "title": "Groundwater",
      "type": "boolean"
    },
    "infrastructure_involved": {
      "title": "Infrastructure Involved",
      "type": "boolean"
    },
    "jbi_involved": {
      "title": "Jbi Involved",
      "type": "boolean"
    },
    "jbi_description": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Jbi Description"
    },
    "non_basin_entity_involved": {
      "title": "Non Basin Entity Involved",
      "type": "boolean"
    },
    "non_basin_entity_description": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Non Basin Entity Description"
    }
  },
  "required": [
    "multiday",
    "date",
    "issue_area",
    "scale_of_impact",
    "groundwater",
    "infrastructure_involved",
    "jbi_involved",
    "non_basin_entity_involved"
  ],
  "title": "EventLead",
  "type": "object"
}
```
"""

# Step 4 - (Inter)action Extraction
# Input: single Event
# Output: interactions, actors, summary, type
STEP4_INTERACTION_EXTRACTION = """\
# (Inter)action Extraction

<!-- TODO: task instructions -->

## Output Format

```json
{
  "$defs": {
    "ActorPair": {
      "properties": {
        "a": {
          "title": "A",
          "type": "string"
        },
        "b": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "B"
        }
      },
      "required": [
        "a"
      ],
      "title": "ActorPair",
      "type": "object"
    },
    "InteractionItem": {
      "description": "One actor/interaction item from Step 4, looped over in Step 5.",
      "properties": {
        "type": {
          "$ref": "#/$defs/InteractionType"
        },
        "actors": {
          "$ref": "#/$defs/ActorPair"
        },
        "summary": {
          "title": "Summary",
          "type": "string"
        }
      },
      "required": [
        "type",
        "actors",
        "summary"
      ],
      "title": "InteractionItem",
      "type": "object"
    },
    "InteractionType": {
      "enum": [
        "action",
        "interaction"
      ],
      "title": "InteractionType",
      "type": "string"
    }
  },
  "description": "Step 4 output.",
  "properties": {
    "interactions": {
      "items": {
        "$ref": "#/$defs/InteractionItem"
      },
      "title": "Interactions",
      "type": "array"
    }
  },
  "required": [
    "interactions"
  ],
  "title": "InteractionExtraction",
  "type": "object"
}
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
