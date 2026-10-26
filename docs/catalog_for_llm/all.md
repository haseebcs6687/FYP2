<!-- IMPORTANT FOR LLM GENERATION: The misconception IDs listed below are the ONLY allowed values for 'misconception_id'. Every distractor option must strictly map to a valid misconception ID from this catalog for the target concept (or null for at most one careless distractor). Never invent or modify IDs. -->

# EduGen Canonical Misconception Catalog (All Modules)

# Module: Classes & Objects (classes-objects)

## class-definition - Defining a Class
summary: A class is the blueprint that declares the fields and methods every object of that type will have.
- class-definition/class-stores-instance-data | blueprint instantiation | Declaring a class allocates storage for instance variables in the class itself rather than in individual instances.
- class-definition/multiple-public-classes | compilation unit | A single Java source file can contain definitions for multiple top-level public classes.
- class-definition/filename-independent | file naming | A public class name does not need to match the name of the containing .java file.
- class-definition/executable-without-main | program entry | Any class definition can be run directly as a standalone application without declaring a public static void main method.

## object-instantiation - Creating Objects
summary: The new keyword allocates an object on the heap, runs a constructor, and returns a reference to it.
- object-instantiation/declaration-creates-object | reference vs object | Declaring an object reference variable automatically creates and initializes the object in memory without calling new.
- object-instantiation/two-new-same-object | instance uniqueness | Two new Foo() expressions called with identical arguments yield the same object and evaluate to true with the == operator.
- object-instantiation/assignment-clones-object | assignment semantics | Assigning one reference variable to another copies all instance fields into a separate, duplicate object.
- object-instantiation/stack-allocated-objects | memory layout | Objects instantiated inside a method body with new are allocated on the method call stack.

## static-members - Static Fields and Methods
summary: Static members belong to the class itself, are shared by every instance, and can be used without an object.
- static-members/instance-copy-of-static | static memory | Each instantiated object maintains its own independent copy of a static class field.
- static-members/static-accesses-this | static context | Static methods possess an implicit this reference and can directly read or write instance fields.
- static-members/static-methods-overridable | method dispatch | Declaring a static method with the same signature in a subclass overrides the superclass static method polymorphically.
- static-members/static-requires-instance | static invocation | Static fields and methods cannot be accessed unless at least one instance of the declaring class has been instantiated.
- static-members/static-variable-reinitialized-on-new | static lifecycle | Static fields are reinitialized back to their initial declaration values every time a new object of that class is created.

## this-keyword - The this Reference
summary: Inside an instance method, this refers to the object the method was invoked on.
- this-keyword/this-refers-to-class | reference target | The this keyword refers to the class definition itself rather than the current instance invoking the method.
- this-keyword/this-in-static-methods | context validity | The this keyword can be legally referenced inside static methods to refer to current state.
- this-keyword/this-call-anywhere-in-constructor | constructor delegation | A this(...) constructor delegation call can appear on any line inside a constructor body.
- this-keyword/this-creates-new-instance | instance identity | Passing or returning this creates a new cloned copy of the current object.

## reference-semantics - References vs Values
summary: Object variables hold references, so assignment copies the reference and two variables can alias one object.
- reference-semantics/pass-by-reference | argument passing | Java passes object arguments using true pass-by-reference parameter passing.
- reference-semantics/reassignment-mutates-caller | parameter reassignment | Reassigning a method parameter variable to point to a new object changes the caller's reference variable.
- reference-semantics/double-equals-compares-content | equality comparison | The == operator on reference variables compares the internal values of the two objects.
- reference-semantics/aliases-are-independent | aliasing mutation | Modifying an object's fields through one reference does not affect the data seen when reading through another alias reference.
- reference-semantics/string-equals-is-double-equals | string equality | The == operator and the .equals() method always produce the exact same result when comparing two String variables.

## object-composition - Composition (has-a)
summary: One object can hold other objects as fields, building bigger behaviour out of smaller parts.
- object-composition/composition-requires-inheritance | has-a vs is-a | A class cannot hold references to other classes unless it explicitly extends them using inheritance.
- object-composition/cascade-deletion | lifecycle dependency | Setting the outer composite object reference to null immediately destroys all member objects it pointed to.
- object-composition/direct-private-access | member visibility | An enclosing composite class can directly read and write private fields of its composed member instances.
- object-composition/composite-automatic-delegation | method delegation | A composite class automatically inherits and exposes all public methods of its inner member objects.

## garbage-collection - Garbage Collection
summary: The JVM reclaims objects that are no longer reachable from any live reference.
- garbage-collection/system-gc-forces-immediate-collection | gc invocation | Calling System.gc() guarantees that the JVM immediately runs garbage collection and cleans all eligible heap memory.
- garbage-collection/nulling-destroys-object | deallocation timing | Setting a reference variable to null immediately deletes the referenced object from memory.
- garbage-collection/stack-variables-garbage-collected | memory reclamation | Local primitive variables and stack frames are cleaned up by the garbage collector.
- garbage-collection/circular-references-leak | reachability analysis | Two unreferenced objects pointing to each other can never be collected by the Java garbage collector.

## local-vs-instance-variables - Local vs Instance Variables
summary: Local variables live on the stack for one method call and must be initialised; instance variables live with the object.
- local-vs-instance-variables/local-variables-default-initialized | variable initialization | Uninitialized local variables declared inside a method automatically receive default values like 0 or null.
- local-vs-instance-variables/local-shadows-permanently | variable shadowing | Declaring a local variable with the same name as an instance field destroys access to the field throughout the method.
- local-vs-instance-variables/locals-retain-state-across-calls | variable lifetime | Local variables retain their assigned values from one invocation of a method to the next.
- local-vs-instance-variables/access-modifiers-on-locals | variable declaration | Local variables can be declared with access modifiers such as public, protected, or private.

## default-values - Default Field Values
summary: Instance and static fields are zero-initialised (0, false, null) before any constructor code runs.
- default-values/boolean-defaults-to-true | primitive defaults | Uninitialized boolean instance fields default to true in Java.
- default-values/strings-default-to-empty | reference defaults | Uninitialized String instance fields default to an empty string ("") instead of null.
- default-values/numeric-defaults-undefined | field initialization | Uninitialized numeric instance fields hold unpredictable garbage memory values like in C/C++.
- default-values/local-primitives-zeroed | scope initialization | Local primitive variables declared in method bodies default to zero if left unassigned.

# Module: Constructors (constructors)

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

# Module: Inheritance (inheritance)

## inheritance-basics - Inheritance Basics
summary: extends creates an is-a relationship so a subclass inherits the accessible members of its superclass.
- inheritance-basics/private-members-inherited | member inheritance | Private fields and methods of a parent class are directly accessible by name in the subclass body.
- inheritance-basics/inheritance-copies-parent-code | inheritance mechanism | Inheritance functions by textually copying the superclass code into the child class bytecode.
- inheritance-basics/subclass-smaller-than-superclass | instance footprint | A subclass object occupies less memory than a superclass object because it is more specialized.
- inheritance-basics/is-a-interchangeable-with-has-a | design semantics | Inheritance should be chosen over composition whenever a class needs utility functionality from another class.
- inheritance-basics/private-fields-not-in-subclass-instance | subclass memory layout | A subclass object does not contain the parent class's private instance variables in memory because it cannot access them directly.

## inheritance-hierarchy - Class Hierarchies
summary: Every class ultimately extends Object, forming a single-rooted tree of types.
- inheritance-hierarchy/object-class-optional | root class | A Java class that does not declare an extends clause has no superclass and does not inherit from Object.
- inheritance-hierarchy/downcasting-always-safe | type casting | Casting a superclass reference variable to a subclass type always succeeds if it compiles.
- inheritance-hierarchy/parent-constructor-not-called | construction sequence | Instantiating a subclass does not execute superclass constructors unless super() is explicitly written.
- inheritance-hierarchy/sibling-classes-interchangeable | type compatibility | Two distinct subclasses that share the same direct parent class can be assigned to each other's references.

## multiple-inheritance - Multiple Inheritance
summary: Java forbids extending two classes (the diamond problem) but allows implementing many interfaces.
- multiple-inheritance/java-supports-multiple-class-inheritance | class extension | A Java class can extend multiple classes simultaneously using a comma-separated extends clause.
- multiple-inheritance/interfaces-solve-diamond-without-rules | default method conflict | Implementing two interfaces with identical default method signatures causes no conflict in Java.
- multiple-inheritance/interface-fields-multiply-inherited | interface constant conflict | A class implementing two interfaces containing fields with the same name inherits both transparently.
- multiple-inheritance/extends-interfaces-syntax | class declaration syntax | Classes use the extends keyword to implement interfaces in Java.

## method-overriding - Method Overriding
summary: A subclass replaces an inherited method by declaring the same signature; @Override makes the intent explicit.
- method-overriding/static-methods-override | static dispatch | Declaring an identical static method in a subclass overrides the superclass static method polymorphically.
- method-overriding/can-reduce-visibility | visibility rules | An overriding method in a subclass can have a more restrictive access modifier than the superclass method.
- method-overriding/override-annotation-required | compiler annotation | Method overriding does not take effect at runtime unless the method is annotated with @Override.
- method-overriding/overriding-by-return-type-only | method signature | Changing only the return type to an unrelated type without altering parameter types produces a valid override.
- method-overriding/overload-override-same | overload vs override | Method overloading and method overriding are synonyms describing the exact same object-oriented mechanism.
- method-overriding/final-methods-overridable | final method inheritance | A method declared with the final keyword can be overridden by a subclass as long as the signature matches.

# Module: Polymorphism (polymorphism)

## method-overloading - Method Overloading
summary: Same method name, different parameter lists - resolved by the compiler at compile time.
- method-overloading/overloading-resolved-at-runtime | dispatch phase | Overloaded method calls are chosen at runtime based on the actual object type passed as argument.
- method-overloading/overload-by-return-type-only | signature definition | Two methods in the same class can share the same name and parameters as long as they return different types.
- method-overloading/varargs-preferred-over-exact | overload priority | The compiler prefers variable-arity (varargs) overloads in preference to exact-match parameter types.
- method-overloading/autoboxing-beats-widening | primitive conversion | When calling an overloaded method with an int, the compiler chooses an Integer overload before a long overload.
- method-overloading/overload-differs-only-by-exceptions | overload throws clause | Two methods with identical names and parameter lists can be overloaded by declaring different exception throws clauses.

## dynamic-method-dispatch - Dynamic Method Dispatch
summary: The JVM picks the overridden method using the object's runtime type, not the reference type.
- dynamic-method-dispatch/fields-dispatched-dynamically | field polymorphism | Accessing a field through a superclass reference variable accesses the overridden subclass field at runtime.
- dynamic-method-dispatch/reference-type-decides-method | dispatch mechanism | When calling an overridden instance method, the compile-time type of the reference decides which method version runs.
- dynamic-method-dispatch/private-methods-dispatched-dynamically | virtual method qualification | Private and final methods participate in runtime dynamic method dispatch.
- dynamic-method-dispatch/compile-time-checks-runtime-type | static type checking | The compiler allows calling subclass-only methods on a parent reference if the underlying runtime object is the subclass.

## runtime-polymorphism - Runtime Polymorphism
summary: A superclass reference can point to any subclass object and behave like it, which is how plug-in behaviour works.
- runtime-polymorphism/downcast-changes-underlying-object | type casting semantics | Casting a superclass reference to a subclass type alters or transforms the underlying object on the heap.
- runtime-polymorphism/instanceof-checks-reference-type | instanceof operator | The instanceof operator tests the compile-time declared type of the reference variable.
- runtime-polymorphism/polymorphism-requires-interfaces | polymorphic prerequisites | Runtime polymorphism can only be achieved using interfaces and cannot be achieved through class inheritance.
- runtime-polymorphism/constructors-dispatched-polymorphically | constructor polymorphism | Calling an overridable method inside a parent constructor runs safely with the subclass fields already initialized.

# Module: Encapsulation (encapsulation)

## access-modifiers - Access Modifiers
summary: public, protected, package-private and private control which code can touch a member.
- access-modifiers/default-means-public | package-private access | Omitting an access modifier on a class member makes it public and accessible to classes across all packages.
- access-modifiers/protected-means-subclass-anywhere-unrestricted | protected scope | A protected member is accessible by any class anywhere in the application without restriction.
- access-modifiers/private-visible-to-subclasses | private inheritance | Private members of a class can be accessed directly by its subclasses.
- access-modifiers/classes-can-be-protected | top-level visibility | Top-level classes can be declared with private or protected access modifiers.
- access-modifiers/package-private-accessible-to-subclasses-everywhere | package-private inheritance | Package-private (default access) members of a parent class can be accessed by subclasses located in any package.

## data-hiding - Data Hiding
summary: Fields are kept private so the class controls every change to its own state.
- data-hiding/getters-make-fields-public | encapsulation purpose | Providing getter and setter methods provides no encapsulation benefit over making fields public.
- data-hiding/data-hiding-is-security-encryption | data protection | Data hiding is a cryptographic security feature designed to encrypt variables in computer memory against attackers.
- data-hiding/final-fields-dont-need-private | immutability vs visibility | Making a mutable object reference public and final provides complete data hiding because the reference cannot be reassigned.
- data-hiding/private-is-per-object | class vs instance scope | A private field cannot be read by another object of the same class (e.g. other.x inside equals).

## getters-setters - Getters and Setters
summary: Accessor and mutator methods expose state deliberately and give the class a place to validate.
- getters-setters/every-field-needs-both | accessor necessity | Proper object-oriented design mandates writing a getter and a setter for every private field in a class.
- getters-setters/setters-cannot-validate | mutator logic | Setters must only perform trivial assignment (this.x = x) and should not validate inputs or throw exceptions.
- getters-setters/getter-returns-clone-automatically | reference leakage | Returning a mutable reference field from a getter automatically creates a safe independent copy.
- getters-setters/boolean-getter-prefixed-with-get | naming convention | Java conventions require boolean accessor methods to be prefixed with 'get' rather than 'is'.

## defensive-copying - Defensive Copying
summary: Copy mutable objects on the way in and on the way out so callers cannot mutate private state.
- defensive-copying/immutable-objects-need-copying | immutable types | Defensive copying is necessary when accepting or returning immutable objects such as String or Integer.
- defensive-copying/clone-is-always-safe | clone method | Calling .clone() on constructor arguments is always safe for creating defensive copies of non-final classes.
- defensive-copying/copying-reference-is-defensive | copy depth | Assigning an incoming array parameter to an instance variable constitutes a defensive copy.
- defensive-copying/only-needed-on-output | input vs output | Defensive copies are only required when returning data in getters, not when accepting parameters in constructors.

## immutability - Immutable Objects
summary: An immutable class has final fields, no setters, and never exposes internal mutable state.
- immutability/final-class-makes-all-fields-immutable | final class | Declaring a class final automatically makes all of its instance fields final and immutable.
- immutability/final-reference-means-immutable-object | reference immutability | Declaring a reference variable final prevents the fields of the referenced object from being altered.
- immutability/immutable-classes-cannot-have-methods | immutable operations | Immutable classes cannot provide operations that transform or compute new values from their data.
- immutability/no-setters-equals-immutable | class immutability | A class is guaranteed to be immutable as long as it declares no setter methods.

## javabeans - The JavaBeans Convention
summary: A bean is a class with a public no-arg constructor, private fields and getX/setX accessors.
- javabeans/requires-special-interface | javabean contract | A class must implement a specific interface called JavaBean to be recognized as a valid JavaBean.
- javabeans/must-not-have-logic | bean methods | JavaBeans are restricted to being pure data holders and cannot contain domain business methods.
- javabeans/constructor-arguments-mandatory | bean instantiation | A JavaBean must have a constructor that initializes all properties at creation time.
- javabeans/property-name-capitalization | property naming | In JavaBeans convention, a getter getAge() corresponds to a property whose logical name is capitalized as 'Age'.

# Module: Abstraction (abstraction)

## abstraction-basics - What Abstraction Is
summary: Abstraction keeps the essential behaviour of a type visible and hides the incidental detail.
- abstraction-basics/abstraction-equals-information-hiding | concept definition | Abstraction and encapsulation are identical concepts that describe the same programming mechanism.
- abstraction-basics/cannot-use-abstract-types-as-variables | abstract reference types | Because an abstract type cannot be instantiated, you cannot declare reference variables or method parameters of that abstract type.
- abstraction-basics/more-abstraction-always-better | design trade-offs | Adding additional layers of abstract classes and interfaces always improves code quality regardless of problem scale.
- abstraction-basics/abstraction-requires-abstract-keyword | language mechanism | Abstraction in Java can only be achieved by explicitly using the abstract keyword.

## abstract-classes - Abstract Classes
summary: An abstract class cannot be instantiated and exists to be extended by concrete subclasses.
- abstract-classes/can-be-instantiated-with-new | instantiation rules | An abstract class can be directly instantiated by invoking new AbstractClass().
- abstract-classes/cannot-have-constructors | constructor existence | Because abstract classes cannot be directly instantiated, they cannot declare constructors.
- abstract-classes/must-have-abstract-methods | method requirements | A class declared with the abstract modifier must contain at least one abstract method.
- abstract-classes/cannot-have-concrete-methods | member implementation | Abstract classes are like old interfaces and cannot provide any fully implemented concrete methods.
- abstract-classes/abstract-class-without-abstract-methods-instantiable | abstract class instantiation | An abstract class that contains only concrete methods and no abstract methods can be instantiated directly with new.

## abstract-methods - Abstract Methods
summary: An abstract method declares a signature with no body and forces every concrete subclass to supply one.
- abstract-methods/can-have-empty-body | method syntax | An abstract method declaration can have a body consisting of empty curly braces ({}).
- abstract-methods/can-be-private-or-final | modifier compatibility | An abstract method can be declared private or final to restrict how subclasses access it.
- abstract-methods/subclass-can-ignore-implementation | subclass obligations | A concrete subclass does not have to implement inherited abstract methods if it chooses not to use them.
- abstract-methods/can-be-declared-in-normal-class | class declaration context | A concrete regular class can declare an abstract method without making the class itself abstract.

## abstract-class-vs-interface - Abstract Class vs Interface
summary: Abstract classes share state and partial implementation; interfaces declare a contract many unrelated types can honour.
- abstract-class-vs-interface/interfaces-can-hold-state | state storage | Interfaces can declare mutable instance variables to hold object state like abstract classes do.
- abstract-class-vs-interface/default-methods-make-interfaces-abstract-classes | type differences | Default methods make interfaces completely identical to abstract classes in modern Java.
- abstract-class-vs-interface/classes-can-extend-multiple-abstract-classes | inheritance capability | A class can extend multiple abstract classes just like it can implement multiple interfaces.
- abstract-class-vs-interface/abstract-must-implement-all-interface-methods | interface implementation | An abstract class that implements an interface must provide concrete implementations for all interface methods.

## design-patterns - Design Patterns
summary: Recurring OOP solutions such as Factory, Strategy, Singleton and Observer built on abstraction and polymorphism.
- design-patterns/lazy-singleton-thread-safe | singleton concurrency | A simple lazily-initialized singleton using an unchecked null check is automatically thread-safe.
- design-patterns/factory-requires-inheritance | factory pattern | The Factory design pattern cannot be used without building an extensive subclass inheritance tree.
- design-patterns/patterns-are-reusable-code-libraries | pattern nature | Design patterns are off-the-shelf code libraries that can be directly imported with an import statement.
- design-patterns/strategy-requires-inheritance | strategy composition | Implementing the Strategy pattern requires the context class to inherit from the strategy algorithm rather than using composition.

# Module: Interfaces (interfaces)

## interface-basics - Interface Basics
summary: An interface is a contract of method signatures that implementing classes must fulfil.
- interface-basics/interface-methods-default-to-package | member visibility | Methods declared in an interface without an access modifier have package-private visibility.
- interface-basics/interface-fields-can-be-mutable | interface fields | Fields declared in an interface can be mutable instance variables modified by implementing classes.
- interface-basics/interface-can-have-constructors | interface lifecycle | Interfaces can define constructor methods to initialize their constant fields.
- interface-basics/interfaces-cannot-extend-other-interfaces | interface inheritance | An interface cannot inherit from another interface using the extends keyword.
- interface-basics/interface-fields-are-instance-variables | interface field modifiers | Fields declared inside an interface without explicit keywords are normal instance variables belonging to implementing objects.

## default-methods - Default and Static Methods
summary: Since Java 8 an interface may ship a default body so it can evolve without breaking implementors.
- default-methods/default-methods-can-modify-instance-state | state access | Default methods can declare and mutate interface-level instance fields.
- default-methods/default-methods-override-object-methods | object method rules | An interface can provide default implementations for equals(), hashCode(), or toString().
- default-methods/implementing-class-must-override-default | override necessity | A class implementing an interface is forced to override all default methods provided by the interface.
- default-methods/default-keyword-optional | method syntax | An interface method with a code body is automatically a default method without writing the default keyword.

## functional-interface - Functional Interfaces
summary: An interface with exactly one abstract method can be implemented by a lambda expression.
- functional-interface/can-have-multiple-abstract-methods | single abstract method | A functional interface can declare two or more abstract methods if it has default methods.
- functional-interface/cannot-have-default-or-static-methods | non-abstract members | Functional interfaces cannot contain any default or static methods.
- functional-interface/annotation-mandatory | annotation role | An interface cannot be used with lambda expressions unless explicitly annotated with @FunctionalInterface.
- functional-interface/lambdas-create-new-classes-at-compile-time | lambda implementation | Every lambda expression generates an anonymous inner class .class file on disk during compilation.

# Module: Exception Handling (exceptions)

## try-catch - try / catch
summary: Guard risky code in try and handle the failure in a catch block matched by exception type.
- try-catch/catch-super-before-subclass | catch block ordering | A catch block for Exception can be placed before a catch block for a subclass like IOException.
- try-catch/try-block-resumes-after-exception | execution flow | After a catch block handles an exception, execution resumes at the next line inside the try block.
- try-catch/catch-blocks-mandatory | block pairing | A try block must always be accompanied by a catch block to compile.
- try-catch/multi-catch-related-types | multi-catch hierarchy | A multi-catch block can legally catch both a subclass and its superclass in the same clause (e.g. catch (IOException | Exception e)).
- try-catch/catch-unthrown-checked-ok | checked exception catch rule | A try-catch block can catch any checked exception like IOException even if the try block code cannot possibly throw it.

## finally-block - The finally Block
summary: finally runs whether or not an exception was thrown, which makes it the place for cleanup.
- finally-block/finally-skipped-on-return | return statement | Executing a return statement inside a try or catch block skips the execution of the finally block.
- finally-block/finally-runs-on-system-exit | jvm termination | The finally block is guaranteed to execute even if System.exit(0) is called in the try block.
- finally-block/finally-return-doesnt-override | finally return value | Returning a value from a finally block does not override the value returned from the preceding try block.
- finally-block/finally-only-runs-on-error | execution trigger | The finally block only executes if an unhandled exception was thrown during the try block.

## checked-vs-unchecked - Checked vs Unchecked
summary: Checked exceptions must be declared or handled; unchecked ones (RuntimeException) need not be.
- checked-vs-unchecked/runtime-exceptions-must-be-declared | throws clause | Methods that might throw RuntimeException subclasses must declare them in their throws clause.
- checked-vs-unchecked/checked-exceptions-occur-at-compile-time | exception occurrence | Checked exceptions represent errors that occur during compilation rather than at runtime.
- checked-vs-unchecked/errors-should-be-caught | error handling | Normal application code should catch java.lang.Error subclasses like OutOfMemoryError or StackOverflowError.
- checked-vs-unchecked/custom-exceptions-always-checked | exception hierarchy | Any custom user-defined exception class in Java is automatically a checked exception.

## exception-throwing - Throwing Exceptions
summary: throw raises an exception object; throws declares that a method may propagate one.
- exception-throwing/throw-and-throws-are-interchangeable | keyword distinction | The throw statement and the throws method clause are synonyms that can be used interchangeably.
- exception-throwing/code-after-throw-reachable | unreachable statements | A statement placed directly after an unconditional throw statement in the same block is legal and executes normally.
- exception-throwing/can-throw-uninstantiated-class | throw argument | The throw statement can take an exception class type directly (e.g. throw IOException;) without using new.
- exception-throwing/override-may-throw-broader-checked | overriding exception rules | An overriding method in a subclass can declare broader checked exceptions in its throws clause than the superclass method declares.

## try-with-resources - try-with-resources
summary: Resources declared in the try header implement AutoCloseable and are closed automatically.
- try-with-resources/close-skipped-on-exception | automatic cleanup | Resources opened in a try-with-resources statement are not closed if an exception is thrown in the try block.
- try-with-resources/works-on-any-object | resource interface | Any arbitrary Java object can be declared inside the try-with-resources parenthesis header.
- try-with-resources/requires-explicit-finally | resource closing | try-with-resources still requires an explicit finally block to call close() on the managed resources.
- try-with-resources/close-called-in-declaration-order | closing sequence | Multiple resources declared in try-with-resources are closed in the exact order they were declared.

## exception-chaining - Exception Chaining
summary: Wrapping a low-level cause inside a higher-level exception preserves the original stack trace.
- exception-chaining/cause-lost-when-wrapped | cause preservation | Catching an exception and throwing a new custom exception permanently erases the original root cause and stack trace.
- exception-chaining/getCause-returns-string-message | cause inspection | Calling e.getCause() returns the exception's text message rather than a Throwable object.
- exception-chaining/initcause-callable-repeatedly | cause initialization | The initCause() method can be invoked multiple times on the same exception instance to reassign or update its underlying cause.
- exception-chaining/only-checked-exceptions-can-be-chained | exception wrapping | Unchecked runtime exceptions cannot have causes attached or participate in exception chaining.

## custom-exceptions - Custom Exceptions
summary: Extending Exception or RuntimeException gives failures a domain-specific, self-documenting type.
- custom-exceptions/must-extend-throwable-directly | inheritance root | Custom user-defined exceptions must extend java.lang.Throwable directly instead of Exception or RuntimeException.
- custom-exceptions/cannot-add-custom-fields | exception state | Custom exceptions can only pass message strings and cannot declare custom fields or context objects.
- custom-exceptions/constructors-inherited | constructor inheritance | A custom exception class automatically inherits Exception's String-message constructor without defining its own.
- custom-exceptions/custom-runtime-requires-throws-clause | runtime exception declaration | Methods throwing custom exceptions extending RuntimeException must declare them in their method throws clause.

## null-pointer-exception - NullPointerException
summary: Dereferencing a null reference throws NPE - the single most common runtime failure in Java.
- null-pointer-exception/primitives-can-be-null | primitive nullability | Primitive variables like int, double, or boolean can be assigned null when no value is present.
- null-pointer-exception/calling-static-on-null-throws-npe | static member on null reference | Invoking a static method through a reference variable that holds null throws a NullPointerException.
- null-pointer-exception/null-string-concatenation-throws | string conversion | Concatenating a null reference variable with a String (e.g. "Item: " + nullRef) throws a NullPointerException.
- null-pointer-exception/null-instanceof-check-throws | null type test | Evaluating (nullVar instanceof String) throws a NullPointerException at runtime.
