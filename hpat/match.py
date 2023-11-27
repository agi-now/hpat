import copy
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict


def _get_match_id():
    return str(uuid.uuid4())


@dataclass(slots=True)
class Match:
    """ Describes match result"""
    concept: str
    value: any
    size: int
    start_idx: int
    id: str = field(repr=False, default_factory=_get_match_id)
    # is this match a result of an assumption
    assumed: bool = False
    # in case match depends on non-confirmed matches,
    # we want to deleted it if matches are invalidated.
    # this only contains direct dependencies, use get_all_dependencies
    # to get all of them
    depends_on_matches: List[str] = field(default_factory=list)
    extractions: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list), repr=False)
    structure: Dict[str, any] = field(default_factory=dict)
    weight: float = 1

    @property
    def end_idx(self):
        return self.start_idx + self.size

    def __repr__(self):
        weight_str = ""
        if self.weight != 1:
            weight_str = f" {self.weight * 100:.0f}%"
        return f"<{self.concept} \"{self.value}\" [{self.size}]{weight_str}>"

    def dependencies_present(self, seq):
        match_ids = seq.get_all_match_ids()
        return not bool(set(self.depends_on_matches).difference(match_ids))

    def get_all_dependencies(self, seq):
        """ Returns recursive match ids that this match depends on"""
        result = []

        for dependency_id in self.depends_on_matches:
            result.append(dependency_id)
            try:
                dependency = seq.match_by_id[dependency_id]
            except KeyError:
                continue
            result.extend(dependency.get_all_dependencies(seq))

        return sorted(list(set(result)))

    @property
    def slot(self):
        return self.start_idx, self.start_idx + self.size


@dataclass
class MatchAssumption:
    sequence_start_idx: int
    sequence_end_idx: int
    assumed_concept: str
    weight: float = 1.0


@dataclass(slots=True)
class MatchState:
    """ Keeps state of matching progress
    Pattern matching is a process of generating matching states.
    When a matching state is fulfilled it can be saved as Match.
    Matching state can be fulfilled many times while going through the sequence.
    This ensures backtracking.
    """
    sequence_idx: int = 0
    pattern_idx: int = 0
    # where the match starts, can't set to 0, because of PRE
    sequence_start_idx: int = None
    # where the match ends
    sequence_end_idx: int = None
    many_optional: bool = False
    # {kb_node_id: [val1, val2]}
    extractions: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list), repr=False)
    assumptions: List['MatchAssumption'] = field(default_factory=list, repr=False)
    depends_on_matches: List[str] = field(default_factory=list, repr=False)
    structure: Dict[str, any] = field(default_factory=dict, repr=False)

    def add_data(self, key, value, many=False):
        if many:
            if key in self.structure:
                # in case of two fields with the same id
                # and first one is not 'many'
                if not isinstance(self.structure[key], list):
                    self.structure[key] = [self.structure[key]]
                self.structure[key].append(value)
            else:
                self.structure[key] = [value]
        else:
            if key in self.structure:
                if not isinstance(self.structure[key], list):
                    self.structure[key] = [self.structure[key]]
                self.structure[key].append(value)
            else:
                self.structure[key] = value

    def get_next(self,
                 next_pattern: int = 1,
                 element_advancement: int = 1,
                 many_optional: bool = False) -> 'MatchState':
        return MatchState(
            sequence_idx=self.sequence_idx + element_advancement,
            pattern_idx=self.pattern_idx + next_pattern,
            sequence_start_idx=self.sequence_start_idx,
            sequence_end_idx=self.sequence_end_idx,
            many_optional=many_optional,
            extractions=copy.deepcopy(self.extractions),
            assumptions=copy.copy(self.assumptions),
            depends_on_matches=copy.copy(self.depends_on_matches),
            structure=copy.deepcopy(self.structure),
        )

    def get_matches(self, seq, concept, weight):
        for match_id in self.depends_on_matches:
            match = seq.match_by_id[match_id]
            weight = min(weight, match.weight)

        structure = {}
        if self.structure:
            structure = {
                "concept": concept,
                "data": copy.deepcopy(self.structure),
            }

        matches = []
        main_match = Match(
            concept=concept,
            value=seq.value[self.sequence_start_idx: self.sequence_end_idx],
            size=self.sequence_end_idx - self.sequence_start_idx,
            start_idx=self.sequence_start_idx,
            assumed=False,
            depends_on_matches=self.depends_on_matches.copy(),
            extractions=copy.deepcopy(self.extractions),
            weight=weight,
            structure=structure
        )
        matches.append(main_match)

        for asmp in self.assumptions:
            matches.append(Match(
                concept=asmp.assumed_concept,
                value=seq.value[asmp.sequence_start_idx: asmp.sequence_end_idx],
                size=asmp.sequence_end_idx - asmp.sequence_start_idx,
                start_idx=asmp.sequence_start_idx,
                assumed=True,
                depends_on_matches=[main_match.id, ],
                weight=asmp.weight,
            ))
        return matches

    def get_value(self, seq):
        return seq.value[self.sequence_start_idx: self.sequence_end_idx]
