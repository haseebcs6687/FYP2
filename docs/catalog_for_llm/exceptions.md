<!-- IMPORTANT FOR LLM GENERATION: The misconception IDs listed below are the ONLY allowed values for 'misconception_id'. Every distractor option must strictly map to a valid misconception ID from this catalog for the target concept (or null for at most one careless distractor). Never invent or modify IDs. -->

# Misconception Catalog - Exception Handling
Detecting, propagating and recovering from failure at runtime.

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
