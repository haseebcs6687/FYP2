"""
=============================================================================
EduGen - Concept Ontology
=============================================================================
Single source of truth for the domain model of the system.

Contains:
  * CONCEPTS          : the 44 canonical concept tags with metadata
  * MODULES           : the 8 OOP modules that group those tags
  * PREREQUISITES     : a directed graph  concept -> [concepts it depends on]
  * helper functions used by every agent and by the RAG retriever

Why this file exists
--------------------
In FYP-1 adaptivity was "topic + difficulty". In FYP-2 adaptivity is driven by
a *concept graph*: the Performance Analysis Agent measures mastery per concept,
and the Adaptive Content Agent walks the prerequisite edges to find the ROOT
CAUSE of a weakness instead of just re-teaching the symptom.
=============================================================================
"""

from collections import OrderedDict

# ─────────────────────────────────────────────────────────────
# Modules  (module_id -> display info)
# ─────────────────────────────────────────────────────────────
MODULES = OrderedDict([
    ("classes-objects", {
        "title": "Classes & Objects",
        "order": 1,
        "blurb": "How a class describes state and behaviour, and how objects come to life.",
        "icon": "cube",
    }),
    ("constructors", {
        "title": "Constructors",
        "order": 2,
        "blurb": "Initialising objects correctly, overloading and chaining constructors.",
        "icon": "spark",
    }),
    ("inheritance", {
        "title": "Inheritance",
        "order": 3,
        "blurb": "Reusing and extending behaviour through class hierarchies.",
        "icon": "tree",
    }),
    ("polymorphism", {
        "title": "Polymorphism",
        "order": 4,
        "blurb": "One reference, many behaviours - compile time and runtime dispatch.",
        "icon": "shuffle",
    }),
    ("encapsulation", {
        "title": "Encapsulation",
        "order": 5,
        "blurb": "Protecting internal state and exposing a deliberate public surface.",
        "icon": "lock",
    }),
    ("abstraction", {
        "title": "Abstraction",
        "order": 6,
        "blurb": "Modelling what something does before deciding how it does it.",
        "icon": "layers",
    }),
    ("interfaces", {
        "title": "Interfaces",
        "order": 7,
        "blurb": "Contracts that let unrelated classes be used interchangeably.",
        "icon": "plug",
    }),
    ("exceptions", {
        "title": "Exception Handling",
        "order": 8,
        "blurb": "Detecting, propagating and recovering from failure at runtime.",
        "icon": "alert",
    }),
])

# Legacy topic names used by the FYP-1 static quiz bank -> module id
LEGACY_TOPIC_TO_MODULE = {
    "Classes & Objects": "classes-objects",
    "Constructors": "constructors",
    "Inheritance": "inheritance",
    "Polymorphism": "polymorphism",
    "Encapsulation": "encapsulation",
    "Abstraction": "abstraction",
    "Interfaces": "interfaces",
    "Exception Handling": "exceptions",
}
MODULE_TO_LEGACY_TOPIC = {v: k for k, v in LEGACY_TOPIC_TO_MODULE.items()}

DIFFICULTIES = ["Easy", "Medium", "Hard"]


def _c(tag, title, module, summary, keywords, prereqs=()):
    return (tag, {
        "tag": tag,
        "title": title,
        "module": module,
        "summary": summary,
        "keywords": list(keywords),
        "prerequisites": list(prereqs),
    })


# ─────────────────────────────────────────────────────────────
# The 44 canonical concept tags
# `keywords` feed the lexical half of the hybrid RAG retriever.
# ─────────────────────────────────────────────────────────────
CONCEPTS = OrderedDict([
    # ── Module 1: Classes & Objects ───────────────────────────
    _c("class-definition", "Defining a Class", "classes-objects",
       "A class is the blueprint that declares the fields and methods every object of that type will have.",
       ["class", "blueprint", "fields", "members", "declaration", "class body", "type"]),
    _c("object-instantiation", "Creating Objects", "classes-objects",
       "The new keyword allocates an object on the heap, runs a constructor, and returns a reference to it.",
       ["new", "instance", "instantiate", "heap", "object creation", "reference"],
       ["class-definition"]),
    _c("static-members", "Static Fields and Methods", "classes-objects",
       "Static members belong to the class itself, are shared by every instance, and can be used without an object.",
       ["static", "class variable", "class method", "shared state", "static block"],
       ["class-definition"]),
    _c("this-keyword", "The this Reference", "classes-objects",
       "Inside an instance method, this refers to the object the method was invoked on.",
       ["this", "current object", "self reference", "shadowing", "implicit parameter"],
       ["object-instantiation"]),
    _c("reference-semantics", "References vs Values", "classes-objects",
       "Object variables hold references, so assignment copies the reference and two variables can alias one object.",
       ["reference", "alias", "pass by value", "null", "shallow copy", "equals vs =="],
       ["object-instantiation"]),
    _c("object-composition", "Composition (has-a)", "classes-objects",
       "One object can hold other objects as fields, building bigger behaviour out of smaller parts.",
       ["composition", "has-a", "aggregation", "delegation", "contains"],
       ["class-definition", "reference-semantics"]),
    _c("garbage-collection", "Garbage Collection", "classes-objects",
       "The JVM reclaims objects that are no longer reachable from any live reference.",
       ["garbage collector", "reachable", "memory", "finalize", "unreferenced"],
       ["reference-semantics"]),
    _c("local-vs-instance-variables", "Local vs Instance Variables", "classes-objects",
       "Local variables live on the stack for one method call and must be initialised; instance variables live with the object.",
       ["local variable", "instance variable", "scope", "lifetime", "stack", "definite assignment"],
       ["class-definition"]),
    _c("default-values", "Default Field Values", "classes-objects",
       "Instance and static fields are zero-initialised (0, false, null) before any constructor code runs.",
       ["default value", "zero", "false", "null", "initialisation"],
       ["local-vs-instance-variables"]),

    # ── Module 2: Constructors ────────────────────────────────
    _c("constructor-basics", "Constructor Basics", "constructors",
       "A constructor has the class name, no return type, and runs once to put a new object into a valid state.",
       ["constructor", "no return type", "initialise", "ctor"],
       ["object-instantiation"]),
    _c("constructor-overloading", "Overloading Constructors", "constructors",
       "Several constructors can coexist as long as their parameter lists differ.",
       ["overload constructor", "parameter list", "signature", "multiple constructors"],
       ["constructor-basics", "method-overloading"]),
    _c("constructor-chaining", "Constructor Chaining", "constructors",
       "this(...) delegates to another constructor in the same class; super(...) delegates to the parent.",
       ["this()", "super()", "delegate", "chaining", "first statement"],
       ["constructor-overloading", "super-keyword"]),
    _c("default-constructor", "The Default Constructor", "constructors",
       "The compiler supplies a no-argument constructor only when the class declares no constructor at all.",
       ["default constructor", "no-arg", "implicit", "compiler generated"],
       ["constructor-basics"]),
    _c("super-keyword", "The super Keyword", "constructors",
       "super refers to the parent part of an object, both for constructors and for overridden methods.",
       ["super", "parent", "base class", "superclass constructor"],
       ["inheritance-basics"]),
    _c("copy-constructor", "Copy Constructors", "constructors",
       "A constructor that takes another instance of the same class and duplicates its state.",
       ["copy constructor", "clone", "duplicate", "deep copy", "shallow copy"],
       ["constructor-overloading", "reference-semantics"]),

    # ── Module 3: Inheritance ─────────────────────────────────
    _c("inheritance-basics", "Inheritance Basics", "inheritance",
       "extends creates an is-a relationship so a subclass inherits the accessible members of its superclass.",
       ["extends", "is-a", "subclass", "superclass", "inherit"],
       ["class-definition"]),
    _c("inheritance-hierarchy", "Class Hierarchies", "inheritance",
       "Every class ultimately extends Object, forming a single-rooted tree of types.",
       ["hierarchy", "Object class", "ancestor", "descendant", "final class"],
       ["inheritance-basics"]),
    _c("multiple-inheritance", "Multiple Inheritance", "inheritance",
       "Java forbids extending two classes (the diamond problem) but allows implementing many interfaces.",
       ["multiple inheritance", "diamond problem", "implements", "single inheritance"],
       ["inheritance-hierarchy", "interface-basics"]),
    _c("method-overriding", "Method Overriding", "inheritance",
       "A subclass replaces an inherited method by declaring the same signature; @Override makes the intent explicit.",
       ["override", "@Override", "same signature", "covariant return", "redefine"],
       ["inheritance-basics"]),

    # ── Module 4: Polymorphism ────────────────────────────────
    _c("method-overloading", "Method Overloading", "polymorphism",
       "Same method name, different parameter lists - resolved by the compiler at compile time.",
       ["overload", "compile time", "static binding", "signature", "parameters"],
       ["class-definition"]),
    _c("dynamic-method-dispatch", "Dynamic Method Dispatch", "polymorphism",
       "The JVM picks the overridden method using the object's runtime type, not the reference type.",
       ["dynamic dispatch", "late binding", "runtime type", "virtual method"],
       ["method-overriding"]),
    _c("runtime-polymorphism", "Runtime Polymorphism", "polymorphism",
       "A superclass reference can point to any subclass object and behave like it, which is how plug-in behaviour works.",
       ["polymorphism", "upcasting", "downcasting", "instanceof", "many forms"],
       ["dynamic-method-dispatch"]),

    # ── Module 5: Encapsulation ───────────────────────────────
    _c("access-modifiers", "Access Modifiers", "encapsulation",
       "public, protected, package-private and private control which code can touch a member.",
       ["public", "private", "protected", "package private", "visibility"],
       ["class-definition"]),
    _c("data-hiding", "Data Hiding", "encapsulation",
       "Fields are kept private so the class controls every change to its own state.",
       ["data hiding", "private fields", "information hiding", "invariant"],
       ["access-modifiers"]),
    _c("getters-setters", "Getters and Setters", "encapsulation",
       "Accessor and mutator methods expose state deliberately and give the class a place to validate.",
       ["getter", "setter", "accessor", "mutator", "validation"],
       ["data-hiding"]),
    _c("defensive-copying", "Defensive Copying", "encapsulation",
       "Copy mutable objects on the way in and on the way out so callers cannot mutate private state.",
       ["defensive copy", "mutable", "leak", "unmodifiable", "protect state"],
       ["getters-setters", "reference-semantics"]),
    _c("immutability", "Immutable Objects", "encapsulation",
       "An immutable class has final fields, no setters, and never exposes internal mutable state.",
       ["immutable", "final", "String", "value object", "thread safe"],
       ["defensive-copying"]),
    _c("javabeans", "The JavaBeans Convention", "encapsulation",
       "A bean is a class with a public no-arg constructor, private fields and getX/setX accessors.",
       ["javabean", "bean", "no-arg constructor", "property", "convention"],
       ["getters-setters", "default-constructor"]),

    # ── Module 6: Abstraction ─────────────────────────────────
    _c("abstraction-basics", "What Abstraction Is", "abstraction",
       "Abstraction keeps the essential behaviour of a type visible and hides the incidental detail.",
       ["abstraction", "essential", "hide complexity", "model"],
       ["class-definition"]),
    _c("abstract-classes", "Abstract Classes", "abstraction",
       "An abstract class cannot be instantiated and exists to be extended by concrete subclasses.",
       ["abstract class", "cannot instantiate", "partial implementation", "base class"],
       ["inheritance-basics", "abstraction-basics"]),
    _c("abstract-methods", "Abstract Methods", "abstraction",
       "An abstract method declares a signature with no body and forces every concrete subclass to supply one.",
       ["abstract method", "no body", "must override", "declaration only"],
       ["abstract-classes", "method-overriding"]),
    _c("abstract-class-vs-interface", "Abstract Class vs Interface", "abstraction",
       "Abstract classes share state and partial implementation; interfaces declare a contract many unrelated types can honour.",
       ["abstract class vs interface", "when to use", "state", "contract", "comparison"],
       ["abstract-classes", "interface-basics"]),
    _c("design-patterns", "Design Patterns", "abstraction",
       "Recurring OOP solutions such as Factory, Strategy, Singleton and Observer built on abstraction and polymorphism.",
       ["design pattern", "factory", "strategy", "singleton", "observer", "template method"],
       ["abstract-class-vs-interface", "runtime-polymorphism"]),

    # ── Module 7: Interfaces ──────────────────────────────────
    _c("interface-basics", "Interface Basics", "interfaces",
       "An interface is a contract of method signatures that implementing classes must fulfil.",
       ["interface", "implements", "contract", "abstract by default", "constant"],
       ["abstraction-basics"]),
    _c("default-methods", "Default and Static Methods", "interfaces",
       "Since Java 8 an interface may ship a default body so it can evolve without breaking implementors.",
       ["default method", "static method in interface", "Java 8", "backward compatible"],
       ["interface-basics"]),
    _c("functional-interface", "Functional Interfaces", "interfaces",
       "An interface with exactly one abstract method can be implemented by a lambda expression.",
       ["functional interface", "lambda", "@FunctionalInterface", "SAM", "method reference"],
       ["interface-basics"]),

    # ── Module 8: Exception Handling ──────────────────────────
    _c("try-catch", "try / catch", "exceptions",
       "Guard risky code in try and handle the failure in a catch block matched by exception type.",
       ["try", "catch", "handle", "multi-catch", "exception type"],
       ["class-definition"]),
    _c("finally-block", "The finally Block", "exceptions",
       "finally runs whether or not an exception was thrown, which makes it the place for cleanup.",
       ["finally", "cleanup", "always runs", "return interaction"],
       ["try-catch"]),
    _c("checked-vs-unchecked", "Checked vs Unchecked", "exceptions",
       "Checked exceptions must be declared or handled; unchecked ones (RuntimeException) need not be.",
       ["checked", "unchecked", "RuntimeException", "throws clause", "compile error"],
       ["try-catch"]),
    _c("exception-throwing", "Throwing Exceptions", "exceptions",
       "throw raises an exception object; throws declares that a method may propagate one.",
       ["throw", "throws", "propagate", "signal failure"],
       ["checked-vs-unchecked"]),
    _c("try-with-resources", "try-with-resources", "exceptions",
       "Resources declared in the try header implement AutoCloseable and are closed automatically.",
       ["try with resources", "AutoCloseable", "close", "resource leak", "Java 7"],
       ["finally-block"]),
    _c("exception-chaining", "Exception Chaining", "exceptions",
       "Wrapping a low-level cause inside a higher-level exception preserves the original stack trace.",
       ["chaining", "cause", "wrap", "getCause", "rethrow"],
       ["exception-throwing"]),
    _c("custom-exceptions", "Custom Exceptions", "exceptions",
       "Extending Exception or RuntimeException gives failures a domain-specific, self-documenting type.",
       ["custom exception", "extends Exception", "domain error", "user defined"],
       ["exception-throwing", "inheritance-basics"]),
    _c("null-pointer-exception", "NullPointerException", "exceptions",
       "Dereferencing a null reference throws NPE - the single most common runtime failure in Java.",
       ["NullPointerException", "NPE", "null check", "Optional", "dereference"],
       ["reference-semantics", "try-catch"]),
])

CANONICAL_CONCEPT_TAGS = list(CONCEPTS.keys())

# Reverse index: module -> [tags]
MODULE_CONCEPTS = {mid: [] for mid in MODULES}
for _tag, _meta in CONCEPTS.items():
    MODULE_CONCEPTS[_meta["module"]].append(_tag)

PREREQUISITES = {tag: meta["prerequisites"] for tag, meta in CONCEPTS.items()}

# Forward index: concept -> concepts that depend on it
DEPENDENTS = {tag: [] for tag in CONCEPTS}
for _tag, _prereqs in PREREQUISITES.items():
    for _p in _prereqs:
        if _p in DEPENDENTS:
            DEPENDENTS[_p].append(_tag)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def is_valid_concept(tag):
    return tag in CONCEPTS


def concept(tag):
    """Return concept metadata, or None."""
    return CONCEPTS.get(tag)


def concept_title(tag):
    meta = CONCEPTS.get(tag)
    return meta["title"] if meta else (tag or "").replace("-", " ").title()


def module_of(tag):
    meta = CONCEPTS.get(tag)
    return meta["module"] if meta else None


def module_title(module_id):
    m = MODULES.get(module_id)
    return m["title"] if m else module_id


def concepts_in_module(module_id):
    return MODULE_CONCEPTS.get(module_id, [])


def prerequisites_of(tag, deep=False, _seen=None):
    """Direct prerequisites, or the full transitive closure when deep=True."""
    direct = PREREQUISITES.get(tag, [])
    if not deep:
        return list(direct)
    _seen = _seen or set()
    out = []
    for p in direct:
        if p in _seen:
            continue
        _seen.add(p)
        out.append(p)
        out.extend(prerequisites_of(p, deep=True, _seen=_seen))
    return out


def learning_order():
    """A teaching-safe ordering of all 44 concepts (topological, module-aware)."""
    ordered, placed = [], set()

    def visit(tag):
        if tag in placed:
            return
        for p in PREREQUISITES.get(tag, []):
            visit(p)
        if tag not in placed:
            placed.add(tag)
            ordered.append(tag)

    for mid in sorted(MODULES, key=lambda m: MODULES[m]["order"]):
        for tag in MODULE_CONCEPTS[mid]:
            visit(tag)
    return ordered


LEARNING_ORDER = learning_order()
CONCEPT_POSITION = {tag: i for i, tag in enumerate(LEARNING_ORDER)}

# The concept a brand-new student starts on.
ENTRY_CONCEPT = "class-definition"


def search_text_for(tag):
    """Text blob used to build a retrieval query for a concept."""
    meta = CONCEPTS.get(tag)
    if not meta:
        return (tag or "").replace("-", " ")
    return "{} {} {}".format(meta["title"], meta["summary"], " ".join(meta["keywords"]))


def normalise_tags(tags):
    """Keep only tags that exist in the canonical vocabulary."""
    if not tags:
        return []
    return [t for t in tags if t in CONCEPTS]


def module_summary():
    """Shape used by the Learn page and the /api/concepts endpoint."""
    out = []
    for mid in sorted(MODULES, key=lambda m: MODULES[m]["order"]):
        meta = MODULES[mid]
        out.append({
            "id": mid,
            "title": meta["title"],
            "blurb": meta["blurb"],
            "icon": meta["icon"],
            "order": meta["order"],
            "legacy_topic": MODULE_TO_LEGACY_TOPIC.get(mid),
            "concepts": [
                {
                    "tag": t,
                    "title": CONCEPTS[t]["title"],
                    "summary": CONCEPTS[t]["summary"],
                    "prerequisites": CONCEPTS[t]["prerequisites"],
                }
                for t in MODULE_CONCEPTS[mid]
            ],
        })
    return out
