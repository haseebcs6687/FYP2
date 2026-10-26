---
title: The JavaBeans Convention
concept: javabeans
module: Encapsulation
tags: javabeans, getters-setters, default-constructor
---

# The JavaBeans Convention

A JavaBean is a class that follows a naming convention so that tools and frameworks can inspect and
populate it reflectively. The rules are: a public no-argument constructor, private fields, public
`getX` / `setX` accessors, and usually `implements Serializable`.

Boolean properties use `isX` rather than `getX`. The property name comes from the accessor name with
the prefix stripped and the first letter lowercased, so `getFirstName` exposes a property called
`firstName`.

The convention matters because Spring, JPA, Jackson and JSP all rely on it. It is deliberately at
odds with immutability - a bean needs a no-argument constructor and setters - so use beans where a
framework demands one and immutable objects elsewhere.

```java
public class StudentBean implements Serializable {
    private String firstName;
    private boolean enrolled;

    public StudentBean() { }                      // required: public, no arguments

    public String getFirstName()            { return firstName; }
    public void   setFirstName(String v)    { this.firstName = v; }

    public boolean isEnrolled()             { return enrolled; }   // is, not get
    public void    setEnrolled(boolean v)   { this.enrolled = v; }
}
```

## Key points
- Public no-argument constructor, private fields, public getX/setX.
- Boolean getters are named isX.
- The property name is the accessor name minus the prefix, first letter lowercased.
- Frameworks depend on the convention; it conflicts with immutability by design.

## Common mistake
Adding a parameterised constructor and removing the no-argument one, which makes the framework fail at runtime with a reflection error.
