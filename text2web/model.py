"""Data shared across compiler phases; no HTML in the AST or symbol table."""

from dataclasses import asdict, dataclass, field


@dataclass
class Diagnostic:
    phase: str
    line: int
    message: str


@dataclass
class Sentence:
    line: int
    original: str
    normalized: str


@dataclass
class Statement:
    kind: str
    line: int
    element_type: str | None = None
    text: str | None = None
    properties: dict[str, str] = field(default_factory=dict)
    reference: str | None = None
    resolved_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    parent_reference: str | None = None
    extended: bool = False


@dataclass
class Element:
    id: str
    type: str
    text: str
    properties: dict[str, str]
    line: int
    parent_id: str | None = None
    name: str | None = None
    extended: bool = False
    auto_foreground: bool = False


@dataclass
class PageNode:
    element_id: str | None = None
    direction: str | None = None
    children: list["PageNode"] = field(default_factory=list)


@dataclass
class PageTree:
    title: str
    children: list[PageNode] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)


@dataclass
class CompilationResult:
    sentences: list[Sentence] = field(default_factory=list)
    tokens: list[dict] = field(default_factory=list)
    ast: list[Statement] = field(default_factory=list)
    symbols: list[Element] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    page_tree: PageTree | None = None
    html: str | None = None
    css: str | None = None
    page_properties: dict[str, str] = field(default_factory=dict)
    auto_page_foreground: bool = False
    focus_id: str | None = None
    focus_explicit: bool = False
    interpretations: list[dict] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.diagnostics and self.html is not None

    def debug_data(self) -> dict:
        return {
            "interpretation": self.interpretations,
            "normalized_input": [asdict(s) for s in self.sentences],
            "tokens": self.tokens,
            "ast": [asdict(s) for s in self.ast],
            "symbol_table": [asdict(s) for s in self.symbols],
            "page_tree": asdict(self.page_tree) if self.page_tree else None,
        }
