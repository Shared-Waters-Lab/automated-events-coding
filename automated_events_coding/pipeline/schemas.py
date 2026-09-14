"""Shared data types passed between pipeline steps.

Field names follow docs/pr-data-pipeline-spec.md as closely as possible, cross-
referenced against docs/SandboxEventsCodingProtocol_2026Update.pdf (the human
coding protocol/codebook this pipeline is automating) where the spec itself is
ambiguous. The spec still flags these schemas as not fully finalized (see its
"Open implementation questions") -- treat the shapes here as a working draft
to revise once real example data and prompt behavior are in hand.
"""

from __future__ import annotations

from enum import Enum

from pydantic import AliasChoices, BaseModel, Field


class RelevanceResult(BaseModel):
    """Step 0 output (classifier, not LLM)."""

    relevant: bool
    meta: dict[str, str]


class Event(BaseModel):
    """A single discrete event extracted from an article in Step 1.

    The Step 1 prompt has the LLM emit ``event_summary``; accept it as a
    validation alias so raw LLM output can be validated directly into this
    model (construction still uses ``text``).
    """

    text: str = Field(alias="event_summary", validation_alias=AliasChoices("event_summary", "text"))


class EventList(BaseModel):
    """Step 1 output."""

    events: list[Event]


class PlaceNames(BaseModel):
    """Step 2 output."""

    place_names: list[str]
    # TODO: confirm this is actually the field Step 2 emits -- the spec leaves
    # the exact source of the "GW mentioned" flag gating Step 2.2 unconfirmed.
    # Note this is distinct from the codebook's own "Groundwater" field (see
    # EventLead.groundwater below) and from CountryBasinLookup.bcode == "GRND"
    # -- see the open question in the spec about how these three relate.
    gw_mentioned: bool


class CountryBasinLookup(BaseModel):
    """Step 2.1 output (rule-based gazetteer lookup, runs unconditionally).

    `bcode` is the TFDD basin code (4 letters), or one of the codebook's
    special values: "GRND" (groundwater-only event, no identifiable
    surface-water international basin), "UNKN" (basin not identifiable),
    "GNRL" (general/global event, not tied to a particular basin). `ccodes`
    are the 3-letter country codes for in-basin actors impacted by the event.
    """

    bcode: str
    ccodes: list[str]


class AquiferLookup(BaseModel):
    """Step 2.2 output (rule-based gazetteer lookup).

    Per the codebook, Aquifer Name is only meaningful when Step 2.1's `bcode`
    resolves to "GRND" -- this conflicts with the diagram, which shows Step
    2.2 gated on an independent "GW mentioned" flag off Step 2 rather than on
    Step 2.1's result. The orchestrator currently follows the diagram (gates
    on PlaceNames.gw_mentioned); revisit once resolved -- see the spec's open
    questions.
    """

    # "Not Specified" per the codebook when BCODE == GRND but the specific
    # IGRAC aquifer can't be determined; None when not applicable at all.
    aquifer_name: str | None = None


class EventDate(BaseModel):
    day: int | None = None
    month: int | None = None
    year: int | None = None


class IssueArea(str, Enum):
    """Controlled vocabulary from the codebook; an event may have several."""

    NOT_ENOUGH_INFO = "0"
    WATER_QUALITY = "Water Quality"
    WATER_QUANTITY = "Water Quantity"
    FISHERIES = "Fisheries"
    HYDROPOWER = "Hydropower"
    DOMESTIC_MUNICIPAL_WATER = "Domestic/Municipal Water"
    NAVIGATION = "Navigation"
    AGRICULTURE = "Agriculture"
    FORESTRY_AND_TIMBER = "Forestry and Timber"
    INFRASTRUCTURE = "Infrastructure"
    CLIMATE_CHANGE = "Climate Change"
    ENVIRONMENT = "Environment"
    FLOOD_MANAGEMENT = "Flood Management"
    DROUGHT_MANAGEMENT = "Drought Management"
    SOCIOECONOMIC_DEVELOPMENT = "Socioeconomic Development"
    FUNDING_AND_FINANCING = "Funding and Financing"
    TERRITORIAL_AND_BORDER_ISSUES = "Territorial and Border Issues"


class ScaleOfImpact(int, Enum):
    """Codebook's "Scale Of Impact" -- descriptive of who's affected, not headcount."""

    LOCAL = 0
    SUB_BASIN = 1
    BASIN = 2
    REGIONAL = 3
    GLOBAL = 4
    UNKNOWN = 99


class EventLead(BaseModel):
    """Step 3 output.

    The spec's `issue_area_and_scale_of_impact` and `groundwater_infrastructure`
    were each a single free-text field; split here into the codebook's actual
    typed fields (Issue Area, Scale Of Impact, Groundwater, Infrastructure
    Involved). `jbi_*`/`non_basin_entity_*` are additional event-level
    attributes from the codebook (Joint Basin Institution, Non-Basin Entity)
    that the spec's Step 3 field list doesn't mention at all -- provisionally
    placed here since Step 3 is the closest existing "event-level" step; move
    them if a better home turns up once the schemas are finalized.
    """

    multiday: bool
    date: EventDate
    issue_area: list[IssueArea]
    scale_of_impact: ScaleOfImpact
    groundwater: bool
    infrastructure_involved: bool
    jbi_involved: bool
    jbi_description: str | None = None
    non_basin_entity_involved: bool
    non_basin_entity_description: str | None = None


class ActorPair(BaseModel):
    a: str
    b: str | None = None  # unset when type == "action" (single actor)


class InteractionType(str, Enum):
    ACTION = "action"
    INTERACTION = "interaction"


class InteractionItem(BaseModel):
    """One actor/interaction item from Step 4, looped over in Step 5."""

    type: InteractionType
    actors: ActorPair
    summary: str


class InteractionExtraction(BaseModel):
    """Step 4 output."""

    interactions: list[InteractionItem]


class ActionID(BaseModel):
    """Step 5.1 output (type == 'action')."""

    entity_name: str
    entity_code: str


class IRMORole(str, Enum):
    """Per-entity role in an interaction, aligned index-wise with entity_codes."""

    INITIATOR = "I"
    RECIPIENT = "R"
    MUTUAL = "M"
    OTHER = "O"
    ACTION_SINGLE_ACTOR = "N"


class InteractionID(BaseModel):
    """Step 5.2 output (type == 'interaction').

    `irmo_codes` is what the spec's ambiguous "dyad_code: string -- per
    entity" field is now understood to mean, per the codebook's IRMO1/IRMO2
    fields (each entity's role: initiator/recipient/mutual/other).
    """

    entity_names: list[str]
    entity_codes: list[str]
    dyad_pairs: tuple[str, str]
    irmo_codes: list[IRMORole]
    bar_scale: float


class EventRecord(BaseModel):
    """Consolidated record assembled from Steps 3 + 5 output, used as Step 6 input.

    TODO: confirm exact composition once Steps 3/5 output shapes are locked
    down -- in particular what "bcode" (a Step 6 primary key per the spec)
    refers to.
    """

    date: EventDate
    entity_list: list[str]
    bcode: str
    dyad_pairs: list[tuple[str, str]]
    issue_area: list[IssueArea]
    bar_scale: float


class DedupOutcome(str, Enum):
    NEW = "new"
    DUPLICATE = "duplicate"
    AMBIGUOUS = "ambiguous"


class DedupResult(BaseModel):
    outcome: DedupOutcome
    matched: EventRecord | None = None
