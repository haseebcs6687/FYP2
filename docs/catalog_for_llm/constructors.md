<!-- IMPORTANT FOR LLM GENERATION: The misconception IDs listed below are the ONLY allowed values for 'misconception_id'. Every distractor option must strictly map to a valid misconception ID from this catalog for the target concept (or null for at most one careless distractor). Never invent or modify IDs. -->

# Misconception Catalog - Constructors
Initialising objects correctly, overloading and chaining constructors.

## constructor-basics - Constructor Basics
summary: A constructor has the class name, no return type, and runs once to put a new object into a valid state.
- constructor-basics/constructors-return-void | constructor signature | Constructor declarations must specify a return type such as void in their method header.
- constructor-basics/constructor-creates-memory | constructor execution | The constructor code itself allocates the object memory on the heap.
- constructor-basics/constructors-inherited | constructor inheritance | Subclasses automatically inherit all constructors defined in their superclass.
- constructor-basics/constructor-callable-like-method | constructor invocation | A constructor can be called directly on an existing object reference like a standard method (e.g. obj.MyClass()).
- constructor-basics/return-statement-illegal-in-constructor | constructor control flow | A constructor cannot contain a return statement under any circumstance.

## constructor-overloading - Overloading Constructors
summary: Several constructors can coexist as long as their parameter lists differ.
- constructor-overloading/overload-by-return-type | overload resolution | Constructors can be overloaded by assigning different return types to each declaration.
- constructor-overloading/same-types-different-names-ok | parameter names | Two constructors with the same parameter types but different parameter names are valid overloads.
- constructor-overloading/default-constructor-preserved | compiler default generation | Defining an overloaded parameterized constructor preserves the compiler-generated zero-argument constructor.
- constructor-overloading/parameter-order-irrelevant | parameter list matching | Changing the sequence of parameter types (e.g. (int, String) vs (String, int)) does not create valid distinct constructor overloads.

## constructor-chaining - Constructor Chaining
summary: this(...) delegates to another constructor in the same class; super(...) delegates to the parent.
- constructor-chaining/multiple-this-calls | delegation limits | A constructor can invoke multiple other constructors in the same class using several this(...) statements.
- constructor-chaining/this-after-statements | chaining placement | A this(...) constructor delegation call can be placed after logging or parameter validation statements.
- constructor-chaining/recursive-chaining-allowed | chain recursion | Two constructors can mutually delegate to one another in an alternating chain using this(...).
- constructor-chaining/chaining-both-this-and-super | constructor dispatch | A single constructor body can explicitly invoke both this(...) and super(...).

## default-constructor - The Default Constructor
summary: The compiler supplies a no-argument constructor only when the class declares no constructor at all.
- default-constructor/always-provided-by-compiler | compiler synthesis | The compiler always generates a zero-argument default constructor for every class.
- default-constructor/custom-no-arg-is-default | terminology | Writing an explicit zero-argument constructor produces what Java technically defines as the default constructor.
- default-constructor/default-ctor-fixes-uninitialized-final | final field initialization | A class with a blank final instance field compiles fine with only the compiler-generated default constructor.
- default-constructor/private-classes-get-public-default | modifier propagation | The default constructor always receives public visibility regardless of the class's access modifier.

## super-keyword - The super Keyword
summary: super refers to the parent part of an object, both for constructors and for overridden methods.
- super-keyword/super-calls-anywhere | super invocation position | An explicit super(...) constructor call can be executed anywhere in the subclass constructor body.
- super-keyword/super-accesses-private-parent | access control | Using super.field allows a subclass to bypass access control and read private fields of its parent.
- super-keyword/super-replaces-this | reference semantics | The super keyword refers to a distinct, separate parent object created alongside the child object.
- super-keyword/super-super-allowed | hierarchy traversal | A subclass can chain super.super to access overridden methods in a grandparent class.

## copy-constructor - Copy Constructors
summary: A constructor that takes another instance of the same class and duplicates its state.
- copy-constructor/java-provides-default-copy | language support | Java automatically synthesizes a default copy constructor for any class that does not declare one.
- copy-constructor/shallow-copy-is-deep | copy depth | Assigning mutable reference fields in a copy constructor (this.arr = other.arr) creates an independent deep copy.
- copy-constructor/copy-constructor-must-clone | cloning relationship | Writing a copy constructor requires the class to implement the Cloneable interface.
- copy-constructor/assignment-copies-object | assignment vs copy | Assigning one object variable to another (b = a) creates an independent copy of the object like a copy constructor does.
