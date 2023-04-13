from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Set

from hpat.match import Match


@dataclass
class DataElement:
    value: Optional[any] = None
    matches: List[Match] = field(default_factory=list)
    disabled: bool = False

    def contains_match(self, match: Match) -> bool:
        for saved in self.matches:
            if saved.concept != match.concept:
                continue
            if saved.size != match.size:
                continue
            if saved.start_idx != match.start_idx:
                continue
            # TODO: we need a better way of specifying concepts that can be duplicated
            if match.concept in {'Sentence', 'MakesSense'} and saved.depends_on_matches != match.depends_on_matches:
                continue

            return True
        return False

    def add_match(self, match: Match) -> bool:
        if not self.contains_match(match):
            self.matches.append(match)
            return True
        return False


@dataclass
class DataSequence:
    value: str
    elements: List[DataElement]
    extractions: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))
    consolidated: bool = False
    match_by_id: Dict[str, Match] = field(default_factory=dict)

    @property
    def size(self):
        return len(self.elements)

    def __post_init__(self):
        for ele in self.elements:
            for match in ele.matches:
                self.match_by_id[match.id] = match

    def add_concept(self, concept, start_idx: int, size: int, weight: float = 1.0) -> bool:
        return self.add_match(Match(
            concept=concept,
            value=self.value[start_idx: start_idx + size],
            size=size,
            start_idx=start_idx,
            weight=weight,
        ))

    def add_match(self, match: Match) -> bool:
        """ Adds match if it is new and returns whether is was added
        May add many overlapping matches with the same concept if they do not align perfectly.
        """
        if not match.dependencies_present(self):
            return False

        self.consolidated = False
        added_new_match = False
        for idx in range(match.size):
            added = self.elements[match.start_idx + idx].add_match(match)
            added_new_match |= added
            if added:
                self.match_by_id[match.id] = match
        return added_new_match

    def revoke_match(self, match_id: str, cascade: bool = True):
        """ Removes match by its id and all matches that depend on it
        This may happen when an assumed match was invalidated.
        """
        self.consolidated = False
        to_revoke = []
        for node in self.elements:
            to_remove = []
            for match in node.matches:
                if match_id in match.depends_on_matches:
                    to_revoke.append(match.id)
                elif match_id == match.id:
                    to_remove.append(match)

            for match in to_remove:
                self.match_by_id.pop(match.id, None)
                node.matches.remove(match)

        if cascade:
            for match_id in to_revoke:
                self.revoke_match(match_id)

    def consolidate(self):
        """ Takes all matches and finds all extractions """
        if self.consolidated:
            return

        self.extractions.clear()

        matches = []
        match_ids = set()

        for node in self.elements:
            for match in node.matches:
                if match.id not in match_ids:
                    matches.append(match)
                    match_ids.add(match.id)

        for match in matches:
            for pattern_node_id, values in match.extractions.items():
                self.extractions[pattern_node_id].extend(values)

        self.consolidated = True

    def display(self, hide=None):
        if hide is None:
            hide = set()

        for node in self.elements:
            matches = sorted(node.matches, key=lambda x: (x.size, len(x.concept)), reverse=True)
            to_display = [repr(x) for x in matches if x.concept not in hide]
            if not to_display:
                to_display = [repr(x) for x in matches if x.concept == 'Character']
            print(', '.join(to_display))

    def to_list(self):
        result = []
        for node in self.elements:
            matches = sorted(node.matches, key=lambda x: (x.size, len(x.concept)), reverse=True)
            result.append([
                (match.concept, match.value)
                for match in matches
            ])
        return result

    def extract(self, pattern_node_id: str):
        if not self.consolidated:
            raise Exception("Must consolidate first")
        return self.extractions.get(pattern_node_id, [])

    def disable_elements(self, concepts):
        if isinstance(concepts, str):
            concepts = [concepts, ]
        for elem in self.elements:
            for match in elem.matches:
                if match.concept in concepts:
                    elem.disabled = True
                    break

    def find_dependant_matches(self, match_id):
        result = []
        for element in self.elements:
            for match in element.matches:
                if match_id in match.depends_on_matches:
                    result.append(match.id)
        return sorted(list(set(result)))

    @classmethod
    def from_string(cls, text):
        return cls(
            value=text,
            elements=[
                DataElement(ch, [Match(concept='Character', value=ch, size=1, start_idx=i)])
                for i, ch in enumerate(text)
            ]
        )

    def get_all_match_ids(self) -> Set[str]:
        match_ids = set()

        for elem in self.elements:
            for match in elem.matches:
                match_ids.add(match.id)

        return match_ids

    def get_match_importance(self, match_id: str) -> int:
        """ Returns number of dependant matches"""
        return len(self.get_dependant_matches(match_id))

    def get_dependant_matches(self, match_id) -> Set[str]:
        deps = set()

        for elem in self.elements:
            for match in elem.matches:
                if match_id in match.depends_on_matches:
                    deps.add(match.id)
                    deps.update(self.get_dependant_matches(match_id.id))

        return deps

    def get_slots(self, concept: str, hierarchy=None) -> List[Tuple[int, int]]:
        """ Returns slots (positions) for a given concept,
        slot is a tuple of (start_idx, end_idx).
        """
        result = []
        for idx, elem in enumerate(self.elements):
            for match in elem.matches:
                if match.start_idx != idx:
                    continue
                if hierarchy is None and match.concept != concept:
                    continue
                elif hierarchy is not None and concept not in hierarchy.get_parents(match.concept) \
                        and match.concept != concept:
                    continue

                result.append((match.start_idx, match.start_idx + match.size))

        return result

    def clean_matches(self, main_match_id: str):
        main_match = self.match_by_id[main_match_id]
        matches_to_remove = self.get_all_match_ids() - set(main_match.get_all_dependencies(self))
        matches_to_remove.remove(main_match.id)
        start = main_match.start_idx
        end = main_match.end_idx
        for match_id in matches_to_remove:
            if match_id not in self.match_by_id:
                continue
            match = self.match_by_id[match_id]
            if not (match.start_idx >= start and match.end_idx <= end):
                continue
            if self.match_by_id[match_id].concept == 'Character':
                continue
            self.revoke_match(match_id)

    def keep_only(self, concepts: list[str], hierarchy=None):
        matches_to_remove = set()
        for idx, elem in enumerate(self.elements):
            for match in elem.matches:
                if match.start_idx != idx:
                    continue
                if match.concept in concepts:
                    continue
                if hierarchy:
                    parents = hierarchy.get_parents(match.concept)
                    if set(parents).intersection(set(concepts)):
                        continue
                matches_to_remove.add(match.id)

        for match_id in matches_to_remove:
            self.revoke_match(match_id, cascade=False)

    def drop_matches(self, concepts: list[str], hierarchy=None, cascade=False):
        matches_to_remove = set()
        for idx, elem in enumerate(self.elements):
            for match in elem.matches:
                if match.start_idx != idx:
                    continue
                if match.concept in concepts:
                    matches_to_remove.add(match.id)
                elif hierarchy:
                    parents = hierarchy.get_parents(match.concept)
                    if set(parents).intersection(set(concepts)):
                        matches_to_remove.add(match.id)

        for match_id in matches_to_remove:
            self.revoke_match(match_id, cascade=False)
