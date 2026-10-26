"""
Writes the concept notes for modules 1-4 into rag/corpus/notes/.
Run:  python scripts/write_notes_1.py   (or just: python scripts/build_corpus.py)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.concepts import CONCEPTS, module_title  # noqa: E402

NOTES = {

# ══════════════ Module 1: Classes & Objects ══════════════
"class-definition": ("""
A class is a blueprint. It declares what data every object of that type will hold and what
operations that object can perform. Writing a class does not create anything at runtime - it
describes a shape that objects will later be stamped from.

A class body holds two kinds of member. Fields (also called instance variables) hold state.
Methods hold behaviour. Both are declared inside the braces of the class, and both can be given
an access modifier that controls who may touch them. A well-designed class keeps its fields
private and exposes only the methods that make sense to the outside world.

The file name must match the public class name exactly, including capitalisation. A file called
BankAccount.java must contain `public class BankAccount`. Java allows other, non-public classes
in the same file, but only one public class per file.
""", """
public class BankAccount {
    // fields - the state every BankAccount carries
    private String owner;
    private double balance;

    // method - the behaviour every BankAccount offers
    public void deposit(double amount) {
        if (amount > 0) {
            balance += amount;
        }
    }

    public double getBalance() {
        return balance;
    }
}
""", [
"A class describes structure; it does not occupy memory until an object is created from it.",
"Fields hold state, methods hold behaviour, and both live inside the class body.",
"A public class must live in a file with exactly the same name.",
"Keeping fields private is the starting point of encapsulation.",
], "Treating the class itself as the thing that stores data. The class is the mould; each object made from it has its own separate copy of the fields."),

"object-instantiation": ("""
An object is created with the `new` keyword. Three things happen in order: memory is allocated on
the heap, the fields are set to their default values, and then a constructor runs to put the
object into a valid starting state. The expression returns a reference to that memory, which you
normally store in a variable.

The variable does not contain the object. It contains a reference that points at the object. This
distinction matters the moment you assign one variable to another or pass an object into a method.

Many objects can be created from one class, and each has its own independent copy of the instance
fields. Changing `a.balance` has no effect whatsoever on `b.balance`.
""", """
BankAccount a = new BankAccount();   // allocate, zero the fields, run the constructor
BankAccount b = new BankAccount();   // a completely separate object

a.deposit(500);

System.out.println(a.getBalance());  // 500.0
System.out.println(b.getBalance());  // 0.0  - b was never touched
""", [
"`new` allocates memory, applies default values, then runs a constructor.",
"The variable holds a reference, not the object itself.",
"Every object gets its own copy of the instance fields.",
"One class can produce any number of objects.",
], "Assuming `BankAccount a;` creates an object. That declares a reference and leaves it `null`; nothing exists until `new` runs."),

"static-members": ("""
A static field or method belongs to the class rather than to any one object. There is exactly one
copy of a static field no matter how many objects exist, and it can be read or written without
creating an object at all.

Use static for things that are genuinely shared: a counter of how many objects have been made, a
constant, or a utility method that needs no instance state. `Math.max` is static because computing
a maximum does not depend on any particular Math object.

A static method cannot use `this` and cannot read instance fields directly, because there is no
object in scope. Calling a static member through an object reference compiles but is misleading -
always qualify it with the class name.
""", """
public class Counter {
    private static int created = 0;       // one copy, shared by every Counter
    private int id;                       // one copy per object

    public Counter() {
        created++;
        id = created;
    }

    public static int getCreated() {      // callable without any object
        return created;
    }
}

new Counter();
new Counter();
System.out.println(Counter.getCreated());   // 2
""", [
"A static member belongs to the class; there is one copy for the whole program.",
"Static methods run without an object and therefore cannot use `this`.",
"Static is right for shared counters, constants and stateless utilities.",
"Call static members through the class name, not through an instance.",
], "Trying to read an instance field from a static method. There is no object, so the compiler rejects it."),

"this-keyword": ("""
Inside an instance method or constructor, `this` is a reference to the object the method was
invoked on. It is an implicit parameter the JVM supplies.

The most common use is to disambiguate when a parameter shadows a field of the same name. If a
constructor takes a parameter called `owner` and the class also has a field called `owner`, plain
`owner` refers to the parameter, and `this.owner` refers to the field.

`this` also lets an object pass itself to another object, and `this(...)` as the first statement
of a constructor delegates to a different constructor in the same class.
""", """
public class BankAccount {
    private String owner;
    private double balance;

    public BankAccount(String owner, double balance) {
        this.owner = owner;       // field = parameter
        this.balance = balance;
    }

    public void transferTo(BankAccount other, double amount) {
        this.balance -= amount;
        other.receive(amount, this);   // hand this object to another object
    }
}
""", [
"`this` refers to the object the current instance method is running on.",
"It resolves shadowing between a parameter and a field of the same name.",
"An object can pass itself to other objects using `this`.",
"`this(...)` as the first statement delegates to another constructor.",
], "Writing `owner = owner;` in a constructor. That assigns the parameter to itself and silently leaves the field null."),

"reference-semantics": ("""
Object variables hold references. Assigning one object variable to another copies the reference,
not the object, so both variables then point at the same object and a change made through one is
visible through the other. This is called aliasing.

Java passes everything by value, but for objects the value being passed is the reference. A method
can therefore mutate the object it was handed, but reassigning the parameter inside the method has
no effect on the caller's variable.

`==` on object references compares the references themselves - are these two variables pointing at
the same object? `equals` compares contents, if the class has overridden it. For Strings and other
value-like types you almost always want `equals`.
""", """
BankAccount a = new BankAccount("Sara", 100);
BankAccount b = a;            // b now aliases the SAME object

b.deposit(50);
System.out.println(a.getBalance());   // 150.0 - a sees the change

String x = new String("hi");
String y = new String("hi");
System.out.println(x == y);        // false - different objects
System.out.println(x.equals(y));   // true  - same contents
""", [
"Assignment copies the reference, so two variables can alias one object.",
"Java is pass-by-value, but for objects the value is the reference.",
"Reassigning a parameter inside a method does not affect the caller.",
"`==` compares references; `equals` compares contents.",
], "Comparing Strings with `==` and getting `true` in small tests because of the string pool, then getting `false` in real code."),

"object-composition": ("""
Composition means one object holds other objects as fields, building larger behaviour out of
smaller pieces. It expresses a has-a relationship: a Car has an Engine, an Order has a list of
LineItems.

Composition is usually preferable to inheritance. Inheritance couples a subclass to the internals
of its parent and cannot be changed at runtime; composition keeps the pieces independent and lets
you swap a collaborator whenever you like. The standard advice is to favour composition over
inheritance and reach for `extends` only when there is a genuine is-a relationship.

Delegation is the natural partner of composition: the outer object forwards a call to the inner
object it holds, adding whatever it needs to on the way.
""", """
public class Engine {
    public void start() { System.out.println("Engine running"); }
}

public class Car {
    private final Engine engine;      // Car HAS-A Engine

    public Car(Engine engine) {
        this.engine = engine;         // injected, so it can be swapped or mocked
    }

    public void start() {
        engine.start();               // delegation
        System.out.println("Car ready");
    }
}
""", [
"Composition models has-a; inheritance models is-a.",
"Held objects can be swapped at runtime, which subclassing cannot do.",
"Delegation forwards work to a held object, optionally adding behaviour.",
"Prefer composition unless the is-a relationship is genuine and stable.",
], "Extending a class just to reuse one method. That drags in the entire parent contract and locks the design."),

"garbage-collection": ("""
Java reclaims memory automatically. An object becomes eligible for collection when no live
reference can reach it any more - not when you finish using it, and not at a moment you can
predict. The garbage collector then frees it at a time of the JVM's choosing.

Setting a reference to `null` does not delete the object; it only removes one path to it. If any
other reference still points there, the object survives. Conversely, an object with no incoming
references is unreachable even if it holds references to other objects itself.

`finalize()` is deprecated and must not be used for cleanup - it may never run. Resources like
files and sockets need explicit closing, which is what try-with-resources and `AutoCloseable` are
for.
""", """
BankAccount a = new BankAccount("Sara", 100);
BankAccount b = a;

a = null;   // the object is still reachable through b - nothing is freed
b = null;   // NOW it is unreachable and eligible for collection

// System.gc() only suggests a collection; it guarantees nothing.
""", [
"Eligibility is about reachability, not about whether you have finished with the object.",
"Nulling one reference frees nothing if another reference remains.",
"Collection timing is decided by the JVM and cannot be forced.",
"Use try-with-resources for files and sockets; never rely on finalize().",
], "Assuming memory is freed the instant a variable goes out of scope, then being surprised by a leak caused by a forgotten reference in a collection."),

"local-vs-instance-variables": ("""
A local variable is declared inside a method and lives on the stack for the duration of that one
call. An instance variable is declared in the class body and lives on the heap alongside the
object, for as long as the object lives.

The rule that catches people out is initialisation. Instance variables are given default values
automatically. Local variables are not: the compiler refuses to read a local variable that it
cannot prove has been assigned. This is called definite assignment analysis, and it is a compile
error, not a runtime one.

Scope follows the same split. A local variable is visible only inside the block that declares it;
an instance variable is visible to every non-static method of the class.
""", """
public class Example {
    private int instanceCount;        // automatically 0

    public void demo() {
        int localCount;               // NOT automatically 0
        // System.out.println(localCount);  // compile error: might not be initialised

        localCount = 5;               // now it is definitely assigned
        System.out.println(localCount + instanceCount);   // 5
    }
}
""", [
"Locals live on the stack for one call; instance variables live with the object.",
"Instance variables get default values; locals must be assigned before use.",
"Reading an unassigned local is a compile error, caught before the program runs.",
"Scope: locals belong to their block, instance variables to the whole object.",
], "Expecting a local `int` to start at 0 the way a field does, and being confused by the compiler error."),

"default-values": ("""
Before any constructor body runs, the JVM zeroes every field of a new object. Numeric types become
0, `char` becomes `'\\u0000'`, `boolean` becomes `false`, and every reference type becomes `null`.
Static fields are given the same treatment when the class is loaded.

This is the reason a field can be read safely before you have explicitly set it, and it is also the
reason an untouched object reference field is `null` rather than some usable empty object.

Local variables are excluded from this. They get no default at all, which is covered under
local vs instance variables.
""", """
public class Defaults {
    int number;          // 0
    double amount;       // 0.0
    boolean active;      // false
    char letter;         // '\\u0000'  (prints as nothing)
    String name;         // null
    int[] values;        // null - the ARRAY reference, not an empty array

    void show() {
        System.out.println(number + " " + active + " " + name);   // 0 false null
        // values[0] = 1;   // NullPointerException - no array was ever created
    }
}
""", [
"Fields are zeroed before the constructor body runs.",
"Numbers become 0, boolean becomes false, references become null.",
"A default reference field is null, not an empty object or empty array.",
"Local variables receive no default and must be assigned explicitly.",
], "Assuming an uninitialised array field is an empty array. It is `null`, and touching it throws a NullPointerException."),

# ══════════════ Module 2: Constructors ══════════════
"constructor-basics": ("""
A constructor is the code that runs when an object is created. It has exactly the same name as the
class and declares no return type, not even `void`. Adding a return type silently turns it into an
ordinary method that will never be called by `new`.

Its job is to leave the object in a valid state. Every field that must have a sensible value should
be set here, and any argument that cannot be accepted should be rejected here, before the object
escapes into the rest of the program. Validating in the constructor is much cheaper than hunting
down a half-built object later.

A constructor cannot be called directly on an existing object. It runs once, as part of `new`.
""", """
public class BankAccount {
    private final String owner;
    private double balance;

    public BankAccount(String owner, double opening) {
        if (owner == null || owner.isBlank()) {
            throw new IllegalArgumentException("Owner is required");
        }
        if (opening < 0) {
            throw new IllegalArgumentException("Opening balance cannot be negative");
        }
        this.owner = owner;
        this.balance = opening;
    }
}
""", [
"Same name as the class, and no return type at all.",
"It runs once, as part of `new`, and cannot be called again later.",
"Its purpose is to guarantee the object is valid from the moment it exists.",
"Rejecting bad arguments here prevents invalid objects from ever escaping.",
], "Writing `public void BankAccount(...)`. That is a normal method that merely shares the class name, so `new` will not run it."),

"constructor-overloading": ("""
A class may declare several constructors as long as their parameter lists differ in number, type or
order. The compiler picks the right one from the arguments at the call site - exactly the same
resolution rule as method overloading.

Overloading lets callers build the object with whatever information they actually have. A short
constructor can supply sensible defaults for the rest.

Parameter names do not participate in overload resolution. Two constructors that take one String
each are a duplicate no matter what you call the parameters.
""", """
public class BankAccount {
    private final String owner;
    private double balance;

    public BankAccount(String owner) {
        this(owner, 0.0);              // delegate, do not duplicate
    }

    public BankAccount(String owner, double opening) {
        this.owner = owner;
        this.balance = opening;
    }
}

new BankAccount("Sara");          // picks the one-argument version
new BankAccount("Sara", 500.0);   // picks the two-argument version
""", [
"Overloads must differ in the number, type or order of parameters.",
"The compiler chooses at compile time from the argument list.",
"Parameter names are irrelevant to overload resolution.",
"Delegate from the short constructor to the full one instead of copying code.",
], "Trying to overload on return type or on parameter names alone. Neither is part of the signature, so it will not compile."),

"constructor-chaining": ("""
Chaining means one constructor calls another so the initialisation logic lives in a single place.
There are two forms. `this(...)` calls another constructor of the same class. `super(...)` calls a
constructor of the parent class.

Either call must be the very first statement of the constructor, and you cannot use both in the
same constructor. If you write neither, the compiler silently inserts a call to the parent's
no-argument constructor - which is a compile error if the parent has no such constructor.

Construction always runs parent-first. The whole super chain completes before the subclass body
executes, which is why a field set in a subclass constructor is not yet available to a method
called from the parent constructor.
""", """
public class Account {
    protected String owner;
    public Account(String owner) { this.owner = owner; }
}

public class SavingsAccount extends Account {
    private double rate;

    public SavingsAccount(String owner) {
        this(owner, 0.05);            // -> the two-arg constructor below
    }

    public SavingsAccount(String owner, double rate) {
        super(owner);                 // MUST be first; runs Account's constructor
        this.rate = rate;
    }
}
""", [
"`this(...)` chains within the class; `super(...)` chains to the parent.",
"Either one must be the first statement, and you cannot use both.",
"Omitting both inserts an implicit `super()` call.",
"Parent constructors always finish before the subclass body starts.",
], "Calling an overridable method from a constructor. The subclass override runs before the subclass fields are initialised, so it sees nulls and zeros."),

"default-constructor": ("""
If a class declares no constructor at all, the compiler generates a no-argument constructor for it.
That generated constructor is public if the class is public, has an empty body, and calls
`super()`.

The moment you declare any constructor yourself, the compiler stops generating it. This is the
usual cause of "constructor BankAccount in class BankAccount cannot be applied to given types":
someone added a two-argument constructor and existing `new BankAccount()` calls stopped compiling.

If you need both, declare the no-argument one explicitly. Frameworks that instantiate objects
reflectively - JavaBeans, JPA, many serialisation libraries - require a no-argument constructor to
be present.
""", """
public class Plain { }                 // compiler supplies Plain()
new Plain();                           // fine

public class Configured {
    private int size;
    public Configured(int size) { this.size = size; }
}
// new Configured();   // compile error - the default constructor is gone

public class Both {
    private int size;
    public Both() { this(10); }        // declared explicitly, so it exists
    public Both(int size) { this.size = size; }
}
""", [
"A default constructor appears only when the class declares no constructor.",
"Declaring any constructor removes the generated one.",
"The generated constructor is empty and calls `super()`.",
"Many frameworks need an explicit no-argument constructor to exist.",
], "Adding a parameterised constructor to an existing class and breaking every `new ClassName()` call elsewhere in the codebase."),

"super-keyword": ("""
`super` gives a subclass access to the parent part of itself. It has two distinct uses.

`super(...)` in a constructor invokes a parent constructor and must be the first statement.
`super.method()` in an ordinary method invokes the parent's version of a method the subclass has
overridden, which is how an override extends behaviour rather than replacing it outright.

`super.method()` is also the escape hatch from infinite recursion: inside an override, a plain call
to `method()` calls the override again.
""", """
public class Account {
    protected double balance;
    public void withdraw(double amount) { balance -= amount; }
    public String describe() { return "Account with " + balance; }
}

public class CheckingAccount extends Account {
    @Override
    public void withdraw(double amount) {
        super.withdraw(amount);          // do the parent's work
        super.withdraw(1.50);            // then add an overdraft fee
    }

    @Override
    public String describe() {
        return "Checking - " + super.describe();   // extend, do not replace
    }
}
""", [
"`super(...)` calls a parent constructor and must come first.",
"`super.method()` calls the parent's version of an overridden method.",
"It lets an override extend the inherited behaviour instead of discarding it.",
"Calling the method without `super.` inside its own override recurses forever.",
], "Forgetting `super.` inside an override and causing a StackOverflowError as the method calls itself."),

"copy-constructor": ("""
A copy constructor takes another instance of the same class and builds a duplicate from it. Java
has no built-in copy syntax, so this is the idiomatic way to duplicate an object - clearer and
safer than `Cloneable` and `clone()`.

The important decision is shallow versus deep. A shallow copy copies each field as-is, so a
reference field ends up pointing at the same underlying object in both copies, and mutating it
through one is visible through the other. A deep copy duplicates the referenced objects too.

For any mutable field, copy deeply. For immutable fields such as String or Integer, sharing the
reference is perfectly safe because nothing can change it.
""", """
public class Order {
    private final String id;                 // immutable - share it
    private final List<String> items;        // mutable - copy it

    public Order(String id, List<String> items) {
        this.id = id;
        this.items = new ArrayList<>(items);
    }

    // copy constructor
    public Order(Order other) {
        this.id = other.id;
        this.items = new ArrayList<>(other.items);   // deep copy
    }
}
""", [
"A copy constructor takes the same type and duplicates its state.",
"Shallow copies share referenced objects; deep copies duplicate them.",
"Copy mutable fields deeply, share immutable ones freely.",
"Preferred over `Cloneable`, which has a famously awkward contract.",
], "Copying a List field by simple assignment. Both objects then share one list, and adding to one adds to the other."),

# ══════════════ Module 3: Inheritance ══════════════
"inheritance-basics": ("""
`extends` declares that one class is a specialised kind of another. The subclass inherits every
accessible member of the superclass and can add its own or replace inherited behaviour.

The relationship must genuinely be is-a. A SavingsAccount is an Account, so inheritance fits. A
Car is not an Engine, so composition fits there instead. Getting this wrong produces hierarchies
that are painful to change.

Private members are not inherited in any useful sense - they exist in the object but the subclass
cannot name them. `protected` exists exactly for members a subclass needs but outside code should
not have. Constructors are never inherited.
""", """
public class Account {
    protected double balance;             // subclasses may touch this
    private String internalId;            // subclasses cannot name this

    public void deposit(double amount) { balance += amount; }
}

public class SavingsAccount extends Account {
    private double rate;

    public void applyInterest() {
        balance += balance * rate;        // inherited protected field
        deposit(0);                       // inherited public method
    }
}
""", [
"`extends` creates an is-a relationship and inherits accessible members.",
"Private members are not accessible to the subclass; protected ones are.",
"Constructors are not inherited, which is why `super(...)` exists.",
"Use inheritance only when the is-a relationship is real.",
], "Using inheritance for code reuse when there is no is-a relationship, producing a subclass that inherits methods that make no sense for it."),

"inheritance-hierarchy": ("""
Java has single inheritance for classes: every class has exactly one direct superclass. A class
with no `extends` clause implicitly extends `Object`, so every class in the language sits in one
tree rooted at `Object`.

That is why every object has `toString()`, `equals()`, `hashCode()` and `getClass()` - they are
inherited from `Object`. Overriding `toString()` is usually the first useful thing a new class
does.

`final` on a class prevents anyone extending it, and `final` on a method prevents anyone
overriding it. `String` is final, which is part of why it is safe to share String references
freely.
""", """
// implicit: class Account extends Object
public class Account {
    private double balance;

    @Override
    public String toString() {            // inherited from Object, now replaced
        return "Account[balance=" + balance + "]";
    }
}

public final class Money { }              // nobody can extend this

public class Base {
    public final void audit() { }         // nobody can override this
}
""", [
"One direct superclass per class; every class descends from Object.",
"toString, equals, hashCode and getClass come from Object.",
"`final` on a class blocks extension; on a method it blocks overriding.",
"The single-rooted tree is what makes `Object` usable as a universal type.",
], "Extending two classes. Java does not allow it - use interfaces when a type needs to honour several contracts."),

"multiple-inheritance": ("""
Java forbids a class extending more than one class. The reason is the diamond problem: if two
parents both provide an implementation of the same method, there is no principled way to decide
which one the child inherits.

Interfaces sidestep this because a class implementing several interfaces inherits contracts, not
state, and historically inherited no implementation at all. A class may implement any number of
interfaces.

Java 8's default methods reintroduced a narrow version of the problem: if two interfaces provide a
default method with the same signature, the compiler forces the implementing class to override it
and choose explicitly using `Interface.super.method()`.
""", """
interface Swimmer { default void move() { System.out.println("swim"); } }
interface Runner  { default void move() { System.out.println("run");  } }

public class Triathlete implements Swimmer, Runner {
    @Override
    public void move() {                  // required - the compiler forces a choice
        Swimmer.super.move();
        Runner.super.move();
    }
}
""", [
"A class extends one class but may implement many interfaces.",
"The diamond problem is why multiple class inheritance is banned.",
"Interfaces carry contracts and, since Java 8, optional default bodies.",
"Conflicting defaults must be resolved explicitly with `Interface.super.method()`.",
], "Expecting `implements A, B` to silently pick one of two conflicting default methods. It is a compile error until you override."),

"method-overriding": ("""
A subclass overrides a method by declaring one with the same name and parameter list as an
inherited method. From then on, calling that method on an object of the subclass runs the
subclass's version, whatever type the reference has.

The rules are strict. The parameter list must match exactly - a different list is an overload, not
an override, and that mistake is very easy to make silently. The return type must be the same or a
subtype (covariant return). The override may not reduce visibility: a public method cannot become
protected. A checked exception list may be narrowed but not widened.

`@Override` costs nothing and turns a silent mistake into a compile error. Use it every time.
""", """
public class Account {
    public double interest() { return 0.0; }
}

public class SavingsAccount extends Account {
    @Override
    public double interest() { return 0.05; }     // real override

    // @Override
    public double interest(int years) { return 0.05 * years; }
    // different parameter list -> this is an OVERLOAD, not an override.
    // Adding @Override here would make the compiler reject it, which is the point.
}
""", [
"Same name and identical parameter list, or it is an overload instead.",
"Return type must match or be a subtype; visibility may not be reduced.",
"Checked exceptions may be narrowed, never widened.",
"`@Override` turns a silent near-miss into a compile error.",
], "Changing a parameter type slightly and creating an overload that never runs, while the inherited version keeps being called."),

# ══════════════ Module 4: Polymorphism ══════════════
"method-overloading": ("""
Overloading means several methods in the same class share a name but differ in their parameter
lists. The compiler decides which one to call by looking at the argument types at the call site.
The decision is made entirely at compile time, which is why it is called static or early binding.

Only the parameter list is part of the signature for this purpose. Return type and parameter names
are not, so two methods that differ only in return type will not compile.

When arguments do not match exactly, the compiler prefers widening a primitive over autoboxing,
and autoboxing over varargs. That order explains most surprising overload choices.
""", """
public class Printer {
    public void print(int value)    { System.out.println("int: " + value); }
    public void print(double value) { System.out.println("double: " + value); }
    public void print(String value) { System.out.println("String: " + value); }
    public void print(Object value) { System.out.println("Object: " + value); }
}

Printer p = new Printer();
p.print(5);         // int
p.print(5.0);       // double
p.print("5");       // String
p.print('a');       // int  - char widens to int before boxing to Character
""", [
"Overloads differ in the number, type or order of parameters.",
"Resolution happens at compile time from the static argument types.",
"Return type and parameter names are not part of the signature.",
"Widening is preferred over boxing, and boxing over varargs.",
], "Expecting overload resolution to consider the runtime type of an argument. It uses the declared type only - that is overriding's job, not overloading's."),

"dynamic-method-dispatch": ("""
When you call an overridden method through a superclass reference, the JVM uses the object's actual
runtime type to decide which implementation runs - not the type of the reference. This is dynamic
dispatch, also called late binding, and it is the mechanism that makes polymorphism work.

Each object carries a pointer to its class's method table, and the call is resolved through that
table at runtime.

Fields are the exception. Field access is resolved at compile time from the reference type, so a
field "hidden" by a subclass does not behave polymorphically. Static methods are also resolved
statically. Only instance methods dispatch dynamically.
""", """
public class Account {
    public double interest() { return 0.0; }
}
public class SavingsAccount extends Account {
    @Override public double interest() { return 0.05; }
}

Account ref = new SavingsAccount();   // reference type Account, runtime type SavingsAccount
System.out.println(ref.interest());   // 0.05 - the runtime type wins

// compile error: the compiler only knows `ref` as an Account
// ref.applyInterest();
""", [
"The runtime type of the object decides which override runs.",
"The reference type decides which methods you are allowed to call.",
"Fields and static methods are bound at compile time, not dynamically.",
"This is the mechanism behind every polymorphic design in Java.",
], "Expecting a hidden field to behave like an overridden method. Field access follows the reference type, so it will not."),

"runtime-polymorphism": ("""
Polymorphism lets one reference type stand for many concrete types. A method that accepts an
`Account` works unchanged with any subclass, including subclasses written after that method was
compiled. This is what makes plug-in style design possible.

Upcasting - assigning a subclass object to a superclass reference - is always safe and implicit.
Downcasting back is explicit and can fail at runtime with a ClassCastException, so guard it with
`instanceof`.

Modern Java offers pattern matching for `instanceof`, which tests and binds in one step and removes
the redundant cast entirely. Needing many `instanceof` checks is usually a sign that the behaviour
belongs on the objects as an overridden method.
""", """
List<Account> accounts = List.of(
    new SavingsAccount(), new CheckingAccount(), new Account());

for (Account a : accounts) {
    System.out.println(a.interest());       // each runs its own version
}

Account a = new SavingsAccount();           // upcast - implicit and safe

if (a instanceof SavingsAccount s) {        // test and bind together
    s.applyInterest();
}
""", [
"One superclass reference can hold any subclass object.",
"Upcasting is implicit; downcasting is explicit and can throw.",
"Guard downcasts with `instanceof`, ideally with pattern matching.",
"A pile of `instanceof` branches usually means the logic belongs in an override.",
], "Downcasting without checking, then getting a ClassCastException as soon as an unexpected subclass appears in the collection."),
}


def write():
    out = Path(__file__).resolve().parent.parent / "rag" / "corpus" / "notes"
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for tag, (prose, code, points, mistake) in NOTES.items():
        meta = CONCEPTS[tag]
        body = "---\ntitle: {}\nconcept: {}\nmodule: {}\ntags: {}\n---\n\n# {}\n\n{}\n\n```java\n{}\n```\n\n## Key points\n{}\n\n## Common mistake\n{}\n".format(
            meta["title"], tag, module_title(meta["module"]),
            ", ".join([tag] + meta["prerequisites"][:2]),
            meta["title"], prose.strip(), code.strip(),
            "\n".join("- " + p for p in points), mistake,
        )
        (out / "{}.md".format(tag)).write_text(body, encoding="utf-8")
        written += 1
    print("wrote {} notes to {}".format(written, out))


if __name__ == "__main__":
    write()
