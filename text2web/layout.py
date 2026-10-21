"""Validate position constraints and build a small row/column page-tree IR."""

from collections import defaultdict, deque

from .model import CompilationResult, Diagnostic, Element, PageNode, PageTree, Statement


def _path(edges: list[tuple[str, str, int]], start: str, end: str) -> list[int] | None:
    pending = deque([(start, [])])
    visited = {start}
    while pending:
        node, lines = pending.popleft()
        if node == end:
            return lines
        for before, after, line in edges:
            if before == node and after not in visited:
                visited.add(after)
                pending.append((after, lines + [line]))
    return None


def _ordered_group(
    members: list[str], edges: list[tuple[str, str, int]], order: dict[str, int],
) -> list[str]:
    incoming = {member: 0 for member in members}
    following: dict[str, list[str]] = defaultdict(list)
    for before, after, _ in edges:
        if before in incoming and after in incoming:
            following[before].append(after)
            incoming[after] += 1
    ready = sorted((item for item, count in incoming.items() if count == 0), key=order.get)
    output = []
    while ready:
        item = ready.pop(0)
        output.append(item)
        for next_item in following[item]:
            incoming[next_item] -= 1
            if incoming[next_item] == 0:
                ready.append(next_item)
                ready.sort(key=order.get)
    return output


def _groups(edges: list[tuple[str, str, int]], order: dict[str, int], direction: str):
    neighbors: dict[str, set[str]] = defaultdict(set)
    for before, after, _ in edges:
        neighbors[before].add(after)
        neighbors[after].add(before)
    groups = []
    visited = set()
    for first in sorted(neighbors, key=order.get):
        if first in visited:
            continue
        pending = [first]
        members = set()
        while pending:
            item = pending.pop()
            if item in members:
                continue
            members.add(item)
            pending.extend(neighbors[item] - members)
        visited.update(members)
        member_list = sorted(members, key=order.get)
        groups.append((set(member_list), PageNode(
            direction=direction,
            children=[PageNode(element_id=item) for item in _ordered_group(member_list, edges, order)],
        )))
    return groups


def _replace_leaf(node: PageNode, element_id: str, replacement: PageNode) -> bool:
    for index, child in enumerate(node.children):
        if child.element_id == element_id:
            node.children[index] = replacement
            return True
        if child.children and _replace_leaf(child, element_id, replacement):
            return True
    return False


def _members(node: PageNode) -> set[str]:
    if node.element_id is not None:
        return {node.element_id}
    return set().union(*(_members(child) for child in node.children)) if node.children else set()


def optimize_page_tree(tree: PageTree) -> PageTree:
    def optimize(node: PageNode) -> PageNode:
        children = []
        for child in node.children:
            optimized = optimize(child)
            if optimized.direction == node.direction and optimized.direction is not None:
                children.extend(optimized.children)
            else:
                children.append(optimized)
        node.children = children
        return node

    roots = []
    for child in tree.children:
        optimized = optimize(child)
        if optimized.direction and len(optimized.children) == 1:
            optimized = optimized.children[0]
        roots.append(optimized)
    tree.children = roots
    return tree


def _build_siblings(result: CompilationResult, title: str) -> PageTree:
    positions = [statement for statement in result.ast if statement.kind == "position"]
    axis_edges: dict[str, list[tuple[str, str, int]]] = {"row": [], "column": []}
    for statement in positions:
        if not statement.resolved_id or not statement.target_id:
            continue
        direction = statement.properties["position"]
        axis = "row" if direction in {"left", "right"} else "column"
        before, after = statement.resolved_id, statement.target_id
        if direction in {"right", "below"}:
            before, after = after, before
        conflicting = _path(axis_edges[axis], after, before)
        if before == after:
            conflicting = [statement.line]
        if conflicting is not None:
            previous_line = conflicting[0] if conflicting else statement.line
            result.diagnostics.append(Diagnostic(
                "layout", statement.line,
                f"Contradicts line {previous_line}: these positions create an impossible {axis} layout.",
            ))
        else:
            axis_edges[axis].append((before, after, statement.line))

    if any(diagnostic.phase == "layout" for diagnostic in result.diagnostics):
        return PageTree(title, [PageNode(element_id=element.id) for element in result.symbols])

    order = {element.id: index for index, element in enumerate(result.symbols)}
    groups = _groups(axis_edges["row"], order, "row") + _groups(axis_edges["column"], order, "column")
    groups.sort(key=lambda group: min(order[item] for item in group[0]))
    roots: list[PageNode] = []
    for member_ids, node in groups:
        overlapping = [
            root for root in roots if _members(root) & member_ids
        ]
        if not overlapping:
            roots.append(node)
            continue
        shared = set.intersection(*(_members(root) & member_ids for root in overlapping))
        if len(overlapping) != 1 or len(shared) != 1:
            result.diagnostics.append(Diagnostic(
                "layout", next((s.line for s in positions if s.target_id in member_ids), 1),
                "This combination of row and column constraints cannot be represented as simple nested layouts.",
            ))
            continue
        root = overlapping[0]
        common_id = next(iter(shared))
        if not _replace_leaf(root, common_id, node):
            result.diagnostics.append(Diagnostic(
                "layout", next((s.line for s in positions if s.target_id in member_ids), 1),
                "This combination of row and column constraints cannot be represented as simple nested layouts.",
            ))

    grouped_ids = set().union(*(_members(root) for root in roots)) if roots else set()
    children = roots + [
        PageNode(element_id=element.id)
        for element in result.symbols if element.id not in grouped_ids
    ]
    children.sort(key=lambda node: min(order[item] for item in _members(node)))
    return PageTree(title, children)


def build_page_tree(result: CompilationResult, title: str) -> PageTree:
    """Run existing position resolution within each explicit parent boundary."""
    elements = {element.id: element for element in result.symbols}
    positions = []
    for statement in result.ast:
        if statement.kind != "position" or not statement.resolved_id or not statement.target_id:
            continue
        source, target = elements[statement.resolved_id], elements[statement.target_id]
        parent = elements.get(source.parent_id)
        if source.parent_id != target.parent_id:
            result.diagnostics.append(Diagnostic("layout", statement.line, 'Positioned elements must share a parent; move them into the same container first.'))
        elif parent and parent.type in {"ul", "ol", "table", "tr", "select", "link"}:
            result.diagnostics.append(Diagnostic("layout", statement.line, 'Layout wrappers are not allowed inside lists, tables, selects or links; use container styles.'))
        else:
            positions.append(statement)

    def children_of(parent_id):
        siblings = [e for e in result.symbols if e.parent_id == parent_id]
        ids = {e.id for e in siblings}
        subset = CompilationResult(symbols=siblings, ast=[s for s in positions if s.resolved_id in ids])
        tree = _build_siblings(subset, title)
        result.diagnostics.extend(subset.diagnostics)

        def populate(node):
            if node.element_id:
                node.children = children_of(node.element_id)
            else:
                for child in node.children:
                    populate(child)
        for node in tree.children:
            populate(node)
        return tree.children

    return PageTree(title, children_of(None), dict(result.page_properties))
