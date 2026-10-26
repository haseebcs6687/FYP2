<!-- IMPORTANT FOR LLM GENERATION: The misconception IDs listed below are the ONLY allowed values for 'misconception_id'. Every distractor option must strictly map to a valid misconception ID from this catalog for the target concept (or null for at most one careless distractor). Never invent or modify IDs. -->

# Misconception Catalog - Polymorphism
One reference, many behaviours - compile time and runtime dispatch.

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
