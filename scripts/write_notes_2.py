"""
Writes the concept notes for modules 5-8 into rag/corpus/notes/.
Run via: python scripts/build_corpus.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.concepts import CONCEPTS, module_title  # noqa: E402

NOTES = {

# ══════════════ Module 5: Encapsulation ══════════════
"access-modifiers": ("""
Java has four levels of access. `private` restricts a member to its own class. Package-private -
written by leaving the modifier off entirely - allows access from any class in the same package.
`protected` adds subclasses, including subclasses in other packages. `public` allows everything.

The default should be `private`. Start there and widen only when something outside genuinely needs
access. Every member you make public becomes part of a contract you have to keep.

Top-level classes can only be public or package-private. `protected` and `private` are not legal on
a top-level class, though they are legal on nested ones.
""", """
public class Account {
    private double balance;          // this class only
    double internalRate;             // package-private: same package
    protected String owner;          // package + subclasses anywhere
    public String accountNumber;     // everyone

    private void audit() { }         // helper nobody else should call
    public double getBalance() { return balance; }   // the deliberate surface
}
""", [
"private < package-private < protected < public, in widening order.",
"Leaving the modifier off means package-private, not public.",
"protected includes subclasses in other packages; package-private does not.",
"Default to private and widen only when there is a real need.",
], "Assuming no modifier means public. It means package-private, which is why code compiles inside the package and fails outside it."),

"data-hiding": ("""
Data hiding means the internal state of an object is not directly reachable from outside. Fields
are private and every change goes through a method the class controls. That control is the whole
point: it is the only place an invariant can be enforced.

If `balance` is public, any code anywhere can set it to a negative number and the class can do
nothing about it. If it is private and only `withdraw` can reduce it, the rule "balance never goes
below zero" can actually be guaranteed.

Hiding also buys freedom to change. As long as the public methods keep their behaviour, the
internal representation can be replaced entirely without breaking any caller.
""", """
public class Account {
    private double balance;          // nobody outside can reach this

    public void withdraw(double amount) {
        if (amount <= 0) throw new IllegalArgumentException("Amount must be positive");
        if (amount > balance) throw new IllegalStateException("Insufficient funds");
        balance -= amount;           // the invariant holds because this is the only path
    }

    public double getBalance() { return balance; }
}
""", [
"Private fields plus controlled methods are what enforce an invariant.",
"A public field cannot be validated, so its rules cannot be guaranteed.",
"Hiding the representation lets it change without breaking callers.",
"Expose behaviour, not storage.",
], "Making a field private and then adding a setter that assigns it with no checks. That is the same exposure with extra steps."),

"getters-setters": ("""
Getters and setters are the controlled doorway to private state. A getter returns a value; a setter
changes one. Their real value is that they give the class a place to validate, convert, log or
compute.

They are not automatic. A field that nothing outside needs should have neither. A field that should
never change after construction should have a getter and no setter. Generating a getter and setter
for every field reproduces public fields with more typing.

A setter that validates is doing useful work. A setter that only assigns is usually a design smell -
ask whether the caller should instead be asking the object to do something.
""", """
public class Account {
    private double balance;
    private String email;

    public double getBalance() { return balance; }     // read-only by design

    public void setEmail(String email) {               // validated on the way in
        if (email == null || !email.contains("@")) {
            throw new IllegalArgumentException("Invalid email");
        }
        this.email = email;
    }

    public String getEmail() { return email; }
    // deliberately NO setBalance - balance changes only through deposit and withdraw
}
""", [
"Accessors exist so the class can validate and control access.",
"Omit the setter when a field should not change after construction.",
"A pass-through setter with no checks adds nothing over a public field.",
"Prefer asking the object to perform an operation over setting its fields.",
], "Auto-generating getters and setters for every field, which breaks encapsulation while appearing to follow it."),

"defensive-copying": ("""
Returning a mutable object from a getter hands the caller a live reference to internal state. They
can then modify it and bypass every check the class has. Accepting a mutable object in a constructor
has the same problem in reverse: the caller keeps their reference and can mutate it afterwards.

The fix is to copy on the way in and on the way out. Copy in the constructor so later changes to the
caller's object do not affect you; copy in the getter so changes to what you return do not affect
you either.

`Collections.unmodifiableList` or `List.copyOf` is a lighter alternative for the outward direction:
the caller gets a view that throws if they try to modify it.
""", """
public class Order {
    private final List<String> items;

    public Order(List<String> items) {
        this.items = new ArrayList<>(items);      // copy IN
    }

    public List<String> getItems() {
        return List.copyOf(items);                // unmodifiable copy OUT
    }

    // Without both copies:
    //   List<String> mine = new ArrayList<>(List.of("a"));
    //   Order o = new Order(mine);
    //   mine.add("b");          // would silently change the order
    //   o.getItems().add("c");  // would silently change the order
}
""", [
"Copy mutable arguments in the constructor and mutable returns in the getter.",
"`final` on the field protects the reference, not the object it points at.",
"`List.copyOf` and `Collections.unmodifiable*` guard the outward direction cheaply.",
"Immutable types such as String need no copying.",
], "Marking a collection field `final` and assuming it is now safe. `final` stops reassignment, not mutation of the contents."),

"immutability": ("""
An immutable object cannot change after construction. Building one takes four things: make the class
`final` so nobody can subclass and add mutable state, make every field `private final`, provide no
setters, and defensively copy any mutable field both in the constructor and in any getter.

The payoff is large. An immutable object is automatically thread-safe, can be shared freely without
defensive copies, is safe as a HashMap key, and can never be observed in a half-updated state.

`String`, all the primitive wrapper types, `LocalDate` and `BigDecimal` all work this way. Operations
that look like mutations return a new object instead - which is why `s.toUpperCase();` on its own
does nothing.
""", """
public final class Money {                       // final: no subclass can add state
    private final String currency;               // private final: set once
    private final List<String> tags;

    public Money(String currency, List<String> tags) {
        this.currency = currency;
        this.tags = List.copyOf(tags);           // copy in
    }

    public List<String> getTags() { return tags; }   // already unmodifiable

    public Money withCurrency(String other) {    // return a new object
        return new Money(other, tags);
    }
}
""", [
"final class, private final fields, no setters, defensive copies.",
"Immutable objects are thread-safe and safe to share without copying.",
"Operations return a new instance rather than mutating the existing one.",
"String and the wrapper types follow exactly this pattern.",
], "Calling `s.trim()` or `s.toUpperCase()` and expecting `s` to change. Strings are immutable - you must assign the result."),

"javabeans": ("""
A JavaBean is a class that follows a naming convention so that tools and frameworks can inspect and
populate it reflectively. The rules are: a public no-argument constructor, private fields, public
`getX` / `setX` accessors, and usually `implements Serializable`.

Boolean properties use `isX` rather than `getX`. The property name comes from the accessor name with
the prefix stripped and the first letter lowercased, so `getFirstName` exposes a property called
`firstName`.

The convention matters because Spring, JPA, Jackson and JSP all rely on it. It is deliberately at
odds with immutability - a bean needs a no-argument constructor and setters - so use beans where a
framework demands one and immutable objects elsewhere.
""", """
public class StudentBean implements Serializable {
    private String firstName;
    private boolean enrolled;

    public StudentBean() { }                      // required: public, no arguments

    public String getFirstName()            { return firstName; }
    public void   setFirstName(String v)    { this.firstName = v; }

    public boolean isEnrolled()             { return enrolled; }   // is, not get
    public void    setEnrolled(boolean v)   { this.enrolled = v; }
}
""", [
"Public no-argument constructor, private fields, public getX/setX.",
"Boolean getters are named isX.",
"The property name is the accessor name minus the prefix, first letter lowercased.",
"Frameworks depend on the convention; it conflicts with immutability by design.",
], "Adding a parameterised constructor and removing the no-argument one, which makes the framework fail at runtime with a reflection error."),

# ══════════════ Module 6: Abstraction ══════════════
"abstraction-basics": ("""
Abstraction is deciding what to expose and what to leave out. The user of a type should see what it
does; how it does it is none of their business and should be free to change.

It is closely related to encapsulation but not the same. Encapsulation is the mechanism - private
fields, controlled access. Abstraction is the design decision about which concepts are worth naming
and what their surface should be.

The practical test is whether a caller can do their job knowing only the method names and their
contracts. A `PaymentProcessor` with `process(Payment)` is a good abstraction. One that forces the
caller to know whether it uses HTTP or a database is a leaky one.
""", """
public interface PaymentProcessor {
    Receipt process(Payment payment);     // WHAT, with no hint of HOW
}

public class StripeProcessor implements PaymentProcessor {
    public Receipt process(Payment payment) {
        // HTTP calls, retries, signing - all invisible to the caller
        return new Receipt();
    }
}

public class CheckoutService {
    private final PaymentProcessor processor;     // depends on the abstraction

    public CheckoutService(PaymentProcessor processor) {
        this.processor = processor;               // any implementation fits
    }
}
""", [
"Abstraction chooses what to expose; encapsulation enforces it.",
"A good abstraction lets the caller work from names and contracts alone.",
"Depending on an abstraction lets implementations be swapped freely.",
"A leaky abstraction forces the caller to know the implementation.",
], "Putting implementation detail in the interface, such as a method named `getHttpClient()`, which locks every implementation into one approach."),

"abstract-classes": ("""
An abstract class is declared with the `abstract` keyword and cannot be instantiated. It exists to
be extended. Its purpose is to hold state and partial implementation that all its subclasses share,
while leaving the parts that differ for them to supply.

It may contain anything a normal class contains - fields, constructors, concrete methods - plus
abstract methods with no body. The constructor is not useless: it runs via `super(...)` when a
concrete subclass is created.

A class must be declared abstract if it has even one abstract method. A class with no abstract
methods may still be declared abstract to say "this is not a complete thing on its own".
""", """
public abstract class Shape {
    private final String name;                    // shared state

    protected Shape(String name) {                // runs from subclass constructors
        this.name = name;
    }

    public abstract double area();                // every subclass must supply this

    public String describe() {                    // shared behaviour, written once
        return name + " with area " + area();
    }
}

public class Circle extends Shape {
    private final double radius;
    public Circle(double radius) { super("Circle"); this.radius = radius; }
    @Override public double area() { return Math.PI * radius * radius; }
}

// new Shape("x");   // compile error - abstract classes cannot be instantiated
""", [
"Abstract classes cannot be instantiated; they are extended.",
"They may hold fields, constructors and concrete methods.",
"One abstract method forces the whole class to be abstract.",
"Their constructor runs through `super(...)` when a subclass is created.",
], "Trying to `new` an abstract class. Instantiate a concrete subclass, or use an anonymous subclass if you really need a one-off."),

"abstract-methods": ("""
An abstract method declares a signature and ends with a semicolon instead of a body. It is a
promise that every concrete subclass will provide an implementation, enforced by the compiler.

Any subclass that does not implement every inherited abstract method must itself be declared
abstract. That is how a partial implementation can sit between the abstract base and the concrete
leaf.

`abstract` cannot be combined with `private`, `static` or `final`. Each combination is a
contradiction: a private method cannot be overridden, a static method is not dispatched
dynamically, and a final method cannot be overridden at all.
""", """
public abstract class Shape {
    public abstract double area();               // no body, ends with ;
    public abstract double perimeter();
}

public abstract class Polygon extends Shape {
    @Override public double perimeter() { return 0; }   // implements one
    // area() is still abstract, so Polygon must stay abstract
}

public class Square extends Polygon {
    private final double side;
    public Square(double side) { this.side = side; }
    @Override public double area() { return side * side; }       // now concrete
}
""", [
"An abstract method has a signature and no body.",
"Every concrete subclass must implement all inherited abstract methods.",
"A subclass that implements only some of them must itself be abstract.",
"abstract cannot combine with private, static or final.",
], "Forgetting one abstract method in a subclass. The compiler then demands the subclass be abstract, which often looks like an unrelated error."),

"abstract-class-vs-interface": ("""
Both let you program against a type rather than an implementation, but they answer different
questions.

Use an abstract class when the implementations are genuinely a family that shares state and code.
It can hold fields and constructors, its members can have any visibility, and a class may extend
only one.

Use an interface when unrelated classes need to honour the same contract. It cannot hold instance
state, its methods are public, and a class may implement as many as it likes. Since Java 8 it can
carry default and static methods, so "interfaces have no implementation" is no longer true.

A common pattern uses both: an interface defines the contract, and an abstract class implements the
tedious parts for implementations that want the help.
""", """
public interface Drawable {                       // contract - anything can honour it
    void draw();
    default void redraw() { draw(); }             // optional shared convenience
}

public abstract class Shape implements Drawable { // family - shares state and code
    protected String colour;                      // interfaces cannot hold this
    protected Shape(String colour) { this.colour = colour; }
    public abstract double area();
}

public class Circle extends Shape implements Serializable {
    public Circle(String colour) { super(colour); }
    @Override public double area() { return 0; }
    @Override public void draw() { }
}
""", [
"Abstract class: shared state and code, single inheritance, any visibility.",
"Interface: contract only, multiple implementation, members implicitly public.",
"Interfaces gained default and static methods in Java 8 but still hold no state.",
"Interface for the contract plus an abstract class for shared plumbing is a common pairing.",
], "Choosing an abstract class for a capability that unrelated types need. It burns the single inheritance slot for no reason."),

"design-patterns": ("""
Design patterns are named solutions to problems that keep recurring in object-oriented design. They
are worth knowing mostly because they give a vocabulary: saying "use a Strategy here" carries a lot
of meaning in three words.

Factory hides which concrete class gets created, so calling code depends only on the interface.
Strategy puts each variant of an algorithm in its own class and lets the caller swap them at
runtime. Singleton restricts a class to one instance. Observer lets objects subscribe to events
from another object. Template Method puts the skeleton of an algorithm in an abstract class and
leaves specific steps to subclasses.

Every one of them rests on abstraction and polymorphism. Use a pattern when it removes duplication
or makes change easier - not because it has a name.
""", """
// Strategy: the algorithm is an object the caller chooses
public interface DiscountPolicy { double apply(double total); }

public class NoDiscount     implements DiscountPolicy { public double apply(double t) { return t; } }
public class StudentDiscount implements DiscountPolicy { public double apply(double t) { return t * 0.8; } }

public class Checkout {
    private DiscountPolicy policy;
    public void setPolicy(DiscountPolicy p) { this.policy = p; }   // swap at runtime
    public double total(double subtotal) { return policy.apply(subtotal); }
}

// Factory: creation detail hidden behind a method
public class ProcessorFactory {
    public static PaymentProcessor create(String type) {
        return "stripe".equals(type) ? new StripeProcessor() : new PaypalProcessor();
    }
}
""", [
"Patterns are shared names for recurring design solutions.",
"Factory hides construction, Strategy makes an algorithm swappable.",
"Singleton restricts instances, Observer distributes events.",
"They all depend on abstraction and polymorphism underneath.",
], "Applying patterns everywhere on principle. A Factory that constructs one class, or a Singleton used as a global variable, adds complexity and removes none."),

# ══════════════ Module 7: Interfaces ══════════════
"interface-basics": ("""
An interface declares a contract: a set of method signatures that any implementing class must
provide. A class states its intent with `implements` and must supply a body for every abstract
method in the interface.

Interface methods are implicitly `public abstract`, and fields are implicitly `public static final`
constants. Writing those modifiers out is legal but redundant.

An interface is a type, so it can be used as a variable type, a parameter type or a return type.
That is the entire point: code written against the interface works with any implementation,
including ones written later.
""", """
public interface Comparable<T> {
    int compareTo(T other);               // implicitly public abstract
}

public class Money implements Comparable<Money> {
    private final int cents;
    public Money(int cents) { this.cents = cents; }

    @Override
    public int compareTo(Money other) {
        return Integer.compare(this.cents, other.cents);
    }
}

Comparable<Money> value = new Money(500);       // the interface is the type
List<Money> prices = new ArrayList<>();
Collections.sort(prices);                       // works because Money honours the contract
""", [
"An interface is a contract of method signatures.",
"Methods are implicitly public abstract; fields are public static final constants.",
"A class may implement any number of interfaces.",
"Interfaces are types, usable anywhere a type is expected.",
], "Trying to declare an interface method `private` or to give an interface instance fields. Neither is allowed."),

"default-methods": ("""
Java 8 added default methods so interfaces could gain new methods without breaking every existing
implementation. A default method has a body, marked with the `default` keyword, and implementing
classes inherit it unless they override it.

This is how `List` gained `sort` and `Iterable` gained `forEach` without breaking the entire
ecosystem overnight.

Interfaces may also declare `static` methods, which belong to the interface itself and are not
inherited by implementors. Since Java 9 they may declare `private` methods too, used only to share
code between the interface's own default methods.
""", """
public interface Greeter {
    String name();                                  // abstract - must be implemented

    default String greet() {                        // inherited unless overridden
        return "Hello, " + name();
    }

    static Greeter of(String name) {                // belongs to the interface itself
        return () -> name;
    }
}

public class Formal implements Greeter {
    public String name() { return "Dr Khan"; }
    @Override public String greet() { return "Good evening, " + name(); }   // override
}
""", [
"A default method carries a body so interfaces can evolve safely.",
"Implementing classes inherit it and may override it.",
"Static interface methods belong to the interface and are not inherited.",
"Two conflicting defaults force the implementor to override and choose.",
], "Treating default methods as a way to add state. An interface still cannot hold instance fields - only constants."),

"functional-interface": ("""
A functional interface has exactly one abstract method. Because there is only one, the compiler can
match a lambda expression or a method reference to it without ambiguity - which is what makes lambda
syntax possible.

Default and static methods do not count towards the one-abstract-method rule, so an interface can
have any number of them and still be functional.

`@FunctionalInterface` is optional but worth adding: it makes the compiler reject the interface if
someone later adds a second abstract method. `java.util.function` supplies the common shapes -
`Predicate<T>`, `Function<T,R>`, `Consumer<T>`, `Supplier<T>` - so you rarely need to write your
own.
""", """
@FunctionalInterface
public interface Validator {
    boolean test(String value);                    // exactly one abstract method
    default Validator and(Validator other) {       // defaults do not break it
        return v -> this.test(v) && other.test(v);
    }
}

Validator notEmpty = v -> v != null && !v.isBlank();      // lambda
Validator hasAt    = v -> v.contains("@");
Validator email    = notEmpty.and(hasAt);

Function<String, Integer> length = String::length;        // method reference
""", [
"Exactly one abstract method makes an interface functional.",
"Default and static methods do not count towards that one.",
"Lambdas and method references are implementations of functional interfaces.",
"`@FunctionalInterface` makes the compiler enforce the rule.",
], "Adding a second abstract method later and breaking every lambda that used the interface, with a confusing error at each call site."),

# ══════════════ Module 8: Exception Handling ══════════════
"try-catch": ("""
A `try` block wraps code that might fail. A `catch` block handles a specific exception type. If
nothing is thrown the catch blocks are skipped entirely; if something is thrown, the JVM finds the
first catch whose type matches and runs it, then continues after the whole statement.

Order matters. Catch blocks are tested top to bottom, so more specific types must come before more
general ones. Putting `catch (Exception e)` first makes every later catch unreachable, and the
compiler rejects it.

Since Java 7 one catch can handle several unrelated types with `|`. Never write an empty catch
block - swallowing an exception hides a bug and gives you nothing to debug from.
""", """
try {
    int[] numbers = new int[3];
    numbers[5] = 10;
    int result = 10 / 0;

} catch (ArrayIndexOutOfBoundsException e) {        // specific first
    System.out.println("Bad index: " + e.getMessage());

} catch (ArithmeticException | NullPointerException e) {   // multi-catch
    System.out.println("Arithmetic or null problem");

} catch (Exception e) {                             // general last
    System.out.println("Something else: " + e.getMessage());
}
""", [
"try wraps risky code; catch handles a matching exception type.",
"Catch blocks are checked in order, so specific types come first.",
"Multi-catch with `|` handles several unrelated types in one block.",
"An empty catch block hides bugs and should never be written.",
], "Catching `Exception` first. Every subsequent catch becomes unreachable and the code will not compile."),

"finally-block": ("""
A `finally` block runs whether or not an exception was thrown, and whether or not one was caught. It
runs even when the try block executes `return`. That makes it the right place for cleanup.

The order is precise: when a try block returns, the return value is computed, then finally runs,
then the method actually returns.

A `return` inside `finally` discards any exception in flight and overrides any return value from the
try block. It silently swallows failures and should be avoided. For closing resources,
try-with-resources is cleaner than a finally block and handles the edge cases correctly.
""", """
public static int demo() {
    try {
        return 1;                 // value 1 is computed and held
    } finally {
        System.out.println("finally always runs");   // then this runs
    }
    // method returns 1
}

public static int bad() {
    try {
        throw new RuntimeException("lost");
    } finally {
        return 2;                 // the exception vanishes - never do this
    }
}
""", [
"finally runs after try and catch, including when try returns.",
"It is the classic place for cleanup that must always happen.",
"A return inside finally swallows exceptions and overrides return values.",
"try-with-resources is the modern replacement for cleanup in finally.",
], "Returning from a finally block and silently destroying an exception that was on its way up the stack."),

"checked-vs-unchecked": ("""
Checked exceptions extend `Exception` but not `RuntimeException`. The compiler insists that you
either catch them or declare them with `throws`. They model conditions a correct program should
anticipate: a missing file, a dropped connection.

Unchecked exceptions extend `RuntimeException`. The compiler says nothing about them. They model
programming errors: a null dereference, a bad index, an illegal argument. `Error` and its subclasses
such as `OutOfMemoryError` are also unchecked and should not be caught.

The practical rule: use a checked exception when the caller can realistically recover, and an
unchecked one when the failure means the code itself is wrong.
""", """
// Checked - the compiler forces a decision
public void read(String path) throws IOException {
    Files.readString(Path.of(path));
}

// Unchecked - no declaration needed
public void setAge(int age) {
    if (age < 0) throw new IllegalArgumentException("Age cannot be negative");
}

try {
    read("missing.txt");
} catch (IOException e) {            // required by the compiler
    System.out.println("Could not read: " + e.getMessage());
}
""", [
"Checked: extends Exception, must be caught or declared.",
"Unchecked: extends RuntimeException, no compiler requirement.",
"Errors are unchecked and are not meant to be caught.",
"Checked for recoverable conditions, unchecked for programming mistakes.",
], "Wrapping everything in `catch (Exception e)` to make the compiler quiet, which also catches the unchecked bugs you needed to see."),

"exception-throwing": ("""
`throw` raises an exception object at the point where the problem is detected. `throws` in a method
signature declares that the method may propagate one to its caller. They are different keywords with
different jobs.

When an exception is thrown, execution of the current method stops immediately and the JVM unwinds
the stack looking for a matching catch. If none is found anywhere, the thread terminates and the
stack trace is printed.

Throw early, at the point the problem is detectable, and include a message that says what was wrong
and what was expected. `throw new IllegalArgumentException("Age was -5, must be 0 or more")` is far
more useful than a bare exception.
""", """
public class Account {
    private double balance;

    public void withdraw(double amount) {            // unchecked - caller need not declare
        if (amount <= 0) {
            throw new IllegalArgumentException("Amount must be positive, got " + amount);
        }
        if (amount > balance) {
            throw new IllegalStateException("Balance is " + balance + ", requested " + amount);
        }
        balance -= amount;
    }

    public void save(String path) throws IOException {   // checked - must be declared
        Files.writeString(Path.of(path), String.valueOf(balance));
    }
}
""", [
"`throw` raises an exception; `throws` declares that one may escape.",
"Throwing stops the method immediately and unwinds the stack.",
"Detect and throw as early as the problem is visible.",
"Messages should state what was wrong and what was expected.",
], "Confusing the two keywords. `throws` in a method body, or `throw` in a signature, will not compile."),

"try-with-resources": ("""
Any object whose class implements `AutoCloseable` can be declared in the parentheses of a `try`
statement. Java then closes it automatically when the block ends, whether it ended normally or
through an exception.

This replaces the old pattern of closing in a `finally` block, and it fixes two bugs that pattern
was prone to: forgetting the null check, and losing the original exception when `close()` itself
threw.

Several resources can be declared, separated by semicolons; they are closed in reverse order of
declaration. If both the body and `close()` throw, the body's exception is the one that propagates
and the close exception is attached to it as a suppressed exception, reachable via
`getSuppressed()`.
""", """
try (BufferedReader reader = Files.newBufferedReader(Path.of("data.txt"));
     PrintWriter writer = new PrintWriter("out.txt")) {

    writer.println(reader.readLine());

} catch (IOException e) {
    System.out.println("I/O failed: " + e.getMessage());
}
// both closed automatically, writer first, even if an exception was thrown

public class Connection implements AutoCloseable {
    @Override public void close() { System.out.println("closed"); }
}
""", [
"Resources declared in the try header are closed automatically.",
"The class must implement AutoCloseable.",
"Multiple resources close in reverse order of declaration.",
"A close() failure is suppressed rather than hiding the real exception.",
], "Still writing the manual finally-and-close pattern, which loses the original exception when close() also fails."),

"exception-chaining": ("""
Chaining wraps a low-level exception inside one that makes sense at the current layer, while keeping
the original as the cause. The caller sees a meaningful type, and the full stack trace of what
actually went wrong is still there.

Every standard exception has a constructor taking a cause, and `getCause()` retrieves it. A printed
stack trace shows the whole chain under "Caused by:".

Wrapping without passing the cause is the mistake to avoid. `throw new DataAccessException("failed")`
discards every piece of diagnostic information the original exception carried, and the resulting
stack trace points at your wrapper instead of the real problem.
""", """
public class UserRepository {
    public User findById(int id) {
        try {
            return database.query(id);

        } catch (SQLException e) {
            // wrap with a meaningful type, KEEP the cause
            throw new DataAccessException("Could not load user " + id, e);
        }
    }
}

public class DataAccessException extends RuntimeException {
    public DataAccessException(String message, Throwable cause) {
        super(message, cause);            // pass it up
    }
}
""", [
"Wrapping translates a low-level failure into a meaningful one.",
"Always pass the original exception as the cause.",
"`getCause()` retrieves it; stack traces show it under 'Caused by:'.",
"Dropping the cause destroys the diagnostic trail.",
], "Catching an exception and throwing a new one without the cause, leaving a stack trace that points nowhere useful."),

"custom-exceptions": ("""
A custom exception is a class extending `Exception` (checked) or `RuntimeException` (unchecked). It
exists to give a failure a name that means something in your domain.

`catch (InsufficientFundsException e)` is self-documenting and can be handled differently from every
other failure. `catch (Exception e)` followed by inspecting the message string is not.

Provide the standard constructors - message, and message plus cause - so callers can chain. Name the
class after the condition, ending in `Exception`. Make it unchecked unless the caller can genuinely
do something about it. Do not create one per method; create one per genuinely distinct condition.
""", """
public class InsufficientFundsException extends RuntimeException {
    private final double shortfall;

    public InsufficientFundsException(double shortfall) {
        super("Short by " + shortfall);
        this.shortfall = shortfall;
    }

    public InsufficientFundsException(String message, Throwable cause) {
        super(message, cause);                  // supports chaining
    }

    public double getShortfall() { return shortfall; }   // structured detail
}

try {
    account.withdraw(500);
} catch (InsufficientFundsException e) {
    System.out.println("Top up " + e.getShortfall());    // handled precisely
}
""", [
"Extend Exception for checked, RuntimeException for unchecked.",
"Name it after the condition and end it in Exception.",
"Provide message and message-plus-cause constructors.",
"Carry structured detail as fields rather than only in the message text.",
], "Creating a separate exception class for every method. A handful of meaningful domain conditions is far more useful than fifty near-identical classes."),

"null-pointer-exception": ("""
A NullPointerException is thrown whenever you dereference a null reference: calling a method on it,
reading a field, indexing it as an array, or unboxing it into a primitive. It is unchecked, so
nothing warns you at compile time.

Since Java 14, helpful NullPointerException messages name the exact expression that was null, which
removes most of the guesswork from a chained call.

Prevention beats catching. Validate arguments at the boundary and fail with a clear
IllegalArgumentException. Return an empty collection rather than null. Use `Optional` for a return
value that genuinely may be absent - but not for fields or parameters. And put the constant first in
a comparison: `"admin".equals(role)` is null-safe, `role.equals("admin")` is not.
""", """
String role = null;

// role.equals("admin");          // NullPointerException
"admin".equals(role);             // false - safe

Objects.requireNonNull(role, "role must not be null");   // fail fast, clear message

Optional<User> user = repository.findById(5);
String name = user.map(User::getName).orElse("unknown");

public List<String> getTags() {
    return tags == null ? List.of() : tags;   // empty, never null
}
""", [
"Thrown on any dereference of null: method call, field access, unboxing.",
"Java 14+ messages name the exact expression that was null.",
"Validate at the boundary with Objects.requireNonNull.",
"Return empty collections, use Optional for absent return values, and compare constant-first.",
], "Catching NullPointerException to keep the program running. It is a bug, not a condition - fix the null instead of hiding it."),
}


def write():
    out = Path(__file__).resolve().parent.parent / "rag" / "corpus" / "notes"
    out.mkdir(parents=True, exist_ok=True)
    for tag, (prose, code, points, mistake) in NOTES.items():
        meta = CONCEPTS[tag]
        body = "---\ntitle: {}\nconcept: {}\nmodule: {}\ntags: {}\n---\n\n# {}\n\n{}\n\n```java\n{}\n```\n\n## Key points\n{}\n\n## Common mistake\n{}\n".format(
            meta["title"], tag, module_title(meta["module"]),
            ", ".join([tag] + meta["prerequisites"][:2]),
            meta["title"], prose.strip(), code.strip(),
            "\n".join("- " + p for p in points), mistake,
        )
        (out / "{}.md".format(tag)).write_text(body, encoding="utf-8")
    print("wrote {} notes".format(len(NOTES)))


if __name__ == "__main__":
    write()
