from dataclasses import dataclass, field
from typing import Optional, List

from hpat.pattern import (
    Pattern,
)
from hpat.hierarchy import (
    HierarchyProvider,
    DictHierarchyProvider,
)
from hpat.data_sequence import (
    DataSequence,
)
from hpat.match import (
    MatchState,
)


@dataclass
class Extractor:
    patterns: List[Pattern]
    hierarchy: Optional[HierarchyProvider] = None
    single_concepts: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.hierarchy is None:
            self.hierarchy = DictHierarchyProvider(children={})

    def apply_once(self, seq: DataSequence) -> bool:
        """ Applies a all patterns to a sequence ones
        and returns whether there were any new matches found
        """
        had_new_matches = False

        for start_idx in range(len(seq.elements)):
            if seq.elements[start_idx].disabled:
                continue
            for pattern in self.patterns:
                if pattern.inside and not \
                        self.check_inside_start_idx(seq, start_idx, pattern.inside):
                    continue

                state = MatchState(
                    sequence_idx=start_idx,
                )
                matches = pattern.match(seq, state, self.hierarchy)
                for match in matches:
                    if pattern.inside and not \
                            self.check_match_is_inside(seq, match, pattern.inside):
                        continue
                    had_new_matches |= seq.add_match(match)

        return had_new_matches

    def check_inside_start_idx(self, seq, idx, inside_concept):
        for match in seq.elements[idx].matches:
            if inside_concept == match.concept or \
                    inside_concept in self.hierarchy.get_parents(match.concept):
                return True
        return False

    def check_match_is_inside(self, seq, match, inside_concept):
        for other in seq.elements[match.start_idx].matches:
            if (inside_concept == other.concept or
                inside_concept in self.hierarchy.get_parents(other.concept)) and \
                    other.start_idx == match.start_idx and \
                    other.size == match.size:
                return True
        return False

    def apply(self, seq: DataSequence):
        """ Applies a all patterns to a sequence till
        no new matches are found
        """
        while self.apply_once(seq):
            pass

        self.apply_single_concepts()
        seq.consolidate()

    def apply_single_concepts(self):
        """ Removes lower-importance concepts that violate single-concept.
        Single-concept means that no more than one child concept of some parent concept
        can occupy the same spot (full spatial match).
        Importance = number of dependent matches.
        """
        if self.hierarchy is None:
            return

        for concept in self.single_concepts:
            # TODO: Two single concepts can share children, check for importance conflicts
            children = self.hierarchy.get_children(concept)

            breakpoint()
            pass
