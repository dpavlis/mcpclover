# CloverDX VALIDATOR — LLM Generation Reference

> Authoritative, generation-ready reference for CloverDX 7.3.x VALIDATOR component.
> All rule XML forms are CONFIRMED WORKING against live schema validation AND visual editor round-trip.
> Supersedes earlier doc — several rule forms in that doc were WRONG.

---

## VISUAL EDITOR COMPATIBILITY — READ FIRST

The CloverDX visual editor will show a warning and reformat any rules XML it considers non-canonical. To avoid that warning, follow these rules strictly when generating the CDATA block.

### DO NOT use XML comments inside the rules CDATA block
Comments are not part of the canonical serialization. The visual editor strips them and warns.
Use the `name` and `customRejectMessage` attributes to convey intent instead.
```
<!-- WRONG: visual editor strips these -->
<!-- This is a range check -->
<interval .../>
```

### DO NOT use blank lines between elements
```
WRONG:                          CORRECT:
<copyAllByName .../>            <copyAllByName .../>
                                <interval .../>
<interval .../>                 <comparison .../>
```

### DO NOT use multi-line attribute formatting
The visual editor collapses attributes to a single line. Write all attributes on one line:
```
WRONG:                          CORRECT:
<interval acceptEmpty="false"   <interval acceptEmpty="false" boundaries="CLOSED_CLOSED" ... to="100" useType="DEFAULT">
          boundaries="CLOSED_CLOSED"
          ...
          to="100" useType="DEFAULT">
```

### Use CDATA wrapping inside `<expression>` child elements
The visual editor serializes expression CTL content wrapped in CDATA:
```xml
<expression ... inputField="My_Field" name="My check" outputField="">
    <expression><![CDATA[isnull($in.0.My_Field) || $in.0.My_Field > 0]]></expression>
</expression>
```
Inside CDATA: write operators literally (`<=`, `>=`, `&&`) — no XML escaping needed.

### Attribute ordering
The visual editor normalizes attributes to alphabetical order. Write attributes alphabetically to avoid diffs. Common ordering: `acceptEmpty` → `boundaries` → `customRejectMessage` → `description` → `enabled` → `from` → `inputField` → `name` → `operator` → `outputField` → `to` → `trimInput` → `useType` → `value`.

### Canonical group/if/then/else child element order
Every `<group>`, `<if>`, `<then>`, `<else>` must have children in this exact order:
1. `<children>` block
2. `<languageSetting .../>`
3. `<customRules>` (only if inline CTL functions needed)
4. `<imports/>`

No extra elements, no reordering.

---

## COMPONENT SKELETON (visual-editor-safe)

```xml
<Node guiName="MyValidator" guiX="400" guiY="80" id="MY_VALIDATOR" type="VALIDATOR">
    <attr name="rules"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<group conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="false" name="All rules" statusCode="">
    <children>
        <copyAllByName customRejectMessage="" description="" enabled="true" inputField="" name="Copy all fields by name" outputField=""/>
    </children>
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
    <imports/>
</group>
]]></attr>
</Node>
```

**Ports:** input `0` → VALIDATOR → output `0` (valid), output `1` (invalid).
**Edge outPort names:** `Port 0 (valid)`, `Port 1 (invalid)`.

---

## ROOT GROUP ATTRIBUTES

| Attribute | Values | Notes |
|---|---|---|
| `conjunction` | `AND` / `OR` | AND = all rules must pass; OR = any rule suffices |
| `lazyEvaluation` | `true` / `false` | true = stop at first failure (faster); false = evaluate all |
| `errorMessageProducer` | `RULES` / `GROUP` | RULES = each child rule emits its own message; GROUP = group emits one message |
| `enabled` | `true` / `false` | |
| `name` | any string | logical label only |

---

## SURFACING REJECTION REASONS — CORRECT PATTERN

**NEVER re-implement validation logic in a downstream Reformat/Map to generate rejection messages.**
The VALIDATOR already knows why a record was rejected. Use the built-in `errorMapping` attribute to capture that information directly.

### How it works

The VALIDATOR has a built-in **error port** (distinct from the invalid port). When a record fails a rule, the VALIDATOR can fire `errorMapping` — a CTL2 transform that receives:
- `$in.0` — the full rejected input record
- `$in.1` — an error info record with fields including `validationMessage` (the `customRejectMessage` text from the rule) and `recordNo` (1-based input record number)

`errorMapping` writes to `$out.1` — which is the **invalid output port** record. This is the correct place to populate `rejectReason`.

Because the root group uses `lazyEvaluation="false"` and sub-groups use `lazyEvaluation="true"`, the VALIDATOR fires one error per failing sub-group. A single input record may therefore produce **multiple** error records on the invalid port (one per failing group). Use a **Denormalizer** keyed on `recordNo` to collapse them back into one output record per input.

### Step 1 — Add `rejectReason` and `recordNo` to the shared metadata

Add two extra fields at the end of the record metadata used by the invalid edge:

```xml
<Field name="rejectReason" type="string"/>
<Field name="recordNo" type="long"/>
```

The same metadata is used for both valid and invalid edges. Valid records will simply have these fields empty/null.

### Step 2 — Add `errorMapping` to the VALIDATOR node

```xml
<Node guiName="MyValidator" guiX="400" guiY="80" id="MY_VALIDATOR" type="VALIDATOR">
    <attr name="rules"><![CDATA[...rules XML...]]></attr>
    <attr name="errorMapping"><![CDATA[//#CTL2

function integer transform() {
    $out.1.* = $in.0.*;
    $out.1.rejectReason = $in.1.validationMessage;
    $out.1.recordNo = $in.1.recordNo;
    return ALL;
}
]]></attr>
</Node>
```

Key points:
- `$out.1.*` = copy all data fields from the rejected input record
- `$out.1.rejectReason = $in.1.validationMessage` = the `customRejectMessage` from the failing rule
- `$out.1.recordNo = $in.1.recordNo` = record number, used as the Denormalizer key
- `return ALL` — required

### Step 3 — Add a Denormalizer to group multiple errors per record

Connect `VALIDATOR:1 (invalid)` → `DENORMALIZER` → `REJECTED_WRITER`.

```xml
<Node guiName="Denormalizer" guiX="820" guiY="375" id="DENORMALIZER" key="recordNo(a)" type="DENORMALIZER">
    <attr name="denormalize"><![CDATA[//#CTL2
string[] reasons = [];

function integer append() {
    reasons.append($in.0.rejectReason);
    return OK;
}

function integer transform() {
    $out.0 = $in.0;
    $out.0.rejectReason = join("|", reasons);
    return OK;
}

function void clean() {
    clear(reasons);
}
]]></attr>
</Node>
```

- `key="recordNo(a)"` — groups by `recordNo` ascending; ensures all errors for one input record are collapsed into one output record
- `append()` — called once per error record in the group; collects messages into a list
- `transform()` — called once per group; writes the consolidated record; `join("|", reasons)` concatenates all messages with `|` separator
- `clean()` — resets the list between groups; **required** or reasons will bleed across groups

### When is the Denormalizer needed?

- **Root group `lazyEvaluation="false"` + sub-groups `lazyEvaluation="true"`** (standard setup): multiple sub-groups can fire independently, so one record can generate multiple error records → Denormalizer needed.
- **Root group `lazyEvaluation="true"`**: stops at first failure → at most one error record per input record → Denormalizer is optional (but harmless to include).

### Edge declarations for this pattern

```xml
<Edge fromNode="READER:0"       id="Edge0" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 0 (output)"  toNode="MY_VALIDATOR:0"/>
<Edge fromNode="MY_VALIDATOR:0" id="Edge1" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 0 (valid)"   toNode="VALID_WRITER:0"/>
<Edge fromNode="MY_VALIDATOR:1" id="Edge2" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 1 (invalid)" toNode="DENORMALIZER:0"/>
<Edge fromNode="DENORMALIZER:0" id="Edge3" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 0 (out)"     toNode="REJECTED_WRITER:0"/>
```

### `customRejectMessage` on `<expression>` elements — KNOWN LIMITATION

Schema validation (checkConfig) rejects `customRejectMessage` as an attribute on `<expression>` rule elements:

```
cvc-complex-type.3.2.2: Attribute 'customRejectMessage' is not allowed to appear in element 'expression'.
```

**Do NOT put `customRejectMessage` on `<expression>` elements.** For expression rules, the `validationMessage` surfaced through `errorMapping` will be derived from the rule's `name` attribute. Word the `name` attribute as a human-readable message to compensate:

```xml
<!-- WRONG — schema error -->
<expression customRejectMessage="Start date must not be after end date." ...>

<!-- CORRECT — use name as the human-readable label; it becomes the error message -->
<expression description="" enabled="true" inputField="Start_Date" name="Start date must not be after end date" outputField="">
    <expression><![CDATA[isnull($in.0.Start_Date) || isnull($in.0.End_Date) || $in.0.Start_Date <= $in.0.End_Date]]></expression>
</expression>
```

All other rule element types (`comparison`, `interval`, `stringLength`, `patternMatch`, `nonEmptyField`, etc.) support `customRejectMessage` normally.

---

## RULE REFERENCE — CONFIRMED WORKING FORMS

All examples below are in visual-editor-canonical format: single-line attributes, no comments, no blank lines, CDATA in expression children.

### 1. copyAllByName
Always place first. Copies all input fields to output by matching name.

```xml
<copyAllByName customRejectMessage="" description="" enabled="true" inputField="" name="Copy all fields by name" outputField=""/>
```

---

### 2. comparison
Compares a field against a **constant value**. Cannot compare two fields — use `expression` for cross-field.

```xml
<comparison acceptEmpty="false" customRejectMessage="Order_Id must be non-negative." description="" enabled="true" inputField="Order_Id" name="Order_Id non-negative" operator="GE" outputField="Order_Id" useType="DEFAULT" value="0">
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
</comparison>
```

**Operators:** `GE` (>=), `GT` (>), `LE` (<=), `LT` (<), `EQ` (=), `NE` (!=)
**Key attributes:** `inputField`, `outputField`, `operator`, `value` (constant), `acceptEmpty`, `useType="DEFAULT"` (always include).
**WRONG operators:** `E` is not valid — use `EQ`. `GTE`/`LTE` do not exist — use `GE`/`LE`.

---

### 3. interval
Range check on numeric or date fields.

```xml
<interval acceptEmpty="false" boundaries="CLOSED_CLOSED" customRejectMessage="Year must be in [1990, 2030]." description="" enabled="true" from="1990" inputField="Year" name="Year range" outputField="Year" to="2030" useType="DEFAULT">
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
</interval>
```

**`boundaries` values:**
- `CLOSED_CLOSED` — from <= x <= to
- `OPEN_CLOSED`   — from < x <= to  (use for "strictly greater than")
- `CLOSED_OPEN`   — from <= x < to
- `OPEN_OPEN`     — from < x < to

For **date fields**, set `languageSetting dateFormat="yyyy-MM-dd" timezone="UTC"` and use ISO date strings in `from`/`to`:

```xml
<interval acceptEmpty="false" boundaries="CLOSED_CLOSED" customRejectMessage="Order_Date must be in 2020." description="" enabled="true" from="2020-01-01" inputField="Order_Date" name="Order_Date within 2020" outputField="Order_Date" to="2020-12-31" useType="DEFAULT">
    <languageSetting dateFormat="yyyy-MM-dd" locale="" numberFormat="" timezone="UTC"/>
</interval>
```

---

### 4. expression
Evaluates a bare CTL2 boolean expression. Use for null checks, cross-field comparisons, and business logic not covered by built-in rules.

```xml
<expression description="" enabled="true" inputField="Start_Date" name="Start date must not be after end date" outputField="">
    <expression><![CDATA[isnull($in.0.Start_Date) || isnull($in.0.End_Date) || $in.0.Start_Date <= $in.0.End_Date]]></expression>
</expression>
```

**CRITICAL rules for `expression`:**
- `inputField` attribute is **required** — set to the primary field even for multi-field expressions
- CTL goes inside a **`<expression>` child element** wrapped in `<![CDATA[...]]>`
- Write a **bare boolean expression** — NO `return`, NO `//#CTL2` header, NO function wrapper
- Inside CDATA: write operators literally (`<=`, `>=`, `&&`) — no XML escaping needed
- Expression must evaluate to `true` for the record to be **valid**
- `expression` element has **no children after** the `<expression>` text node — do not add `<languageSetting>`
- **`customRejectMessage` is NOT valid on `<expression>` elements** — omit it; use a descriptive `name` attribute instead (see section above)

**WRONG forms (all invalid):**
```
expression="$in.0.x > 0"                           <- as XML attribute
<expression>return $in.0.x > 0;</expression>        <- return keyword
<expression>//#CTL2\n$in.0.x > 0</expression>      <- CTL2 header
<expression customRejectMessage="..." ...>           <- customRejectMessage not valid on expression
<expression>$in.0.x > 0</expression>
<languageSetting .../>                               <- languageSetting after expression child
</expression>
```

**Cross-field example:**
```xml
<expression description="" enabled="true" inputField="Order_Date" name="Order_Date must fall within campaign window" outputField="">
    <expression><![CDATA[isnull($in.0.Order_Date) || isnull($in.0.Campaign_Start) || isnull($in.0.Campaign_End) || ($in.0.Order_Date >= $in.0.Campaign_Start && $in.0.Order_Date <= $in.0.Campaign_End)]]></expression>
</expression>
```

---

### 5. stringLength
Validates string length. Also rejects null/empty when `acceptEmpty="false"`.

```xml
<stringLength acceptEmpty="false" customRejectMessage="Store_Name must not be blank." description="" enabled="true" inputField="Store_Name" max="200" min="1" name="Store_Name not blank" outputField="Store_Name" trimInput="true">
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
</stringLength>
```

**CRITICAL:** Attributes are `min` and `max` — NOT `minLength`/`maxLength`.

---

### 6. patternMatch
Validates a string against a Java regex. Use a literal string for exact match, `^value$` for anchored match.

```xml
<patternMatch acceptEmpty="false" customRejectMessage="Store_Country must be 'USA'." description="" enabled="true" ignoreCase="false" inputField="Store_Country" name="Store_Country is USA" outputField="Store_Country" trimInput="false">
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
    <pattern>USA</pattern>
</patternMatch>
```

**CRITICAL:** Pattern goes in a `<pattern>` child element — NOT as an XML attribute.
**Enum-style match** (one of several values): `<pattern>^(USA|CAN|MEX)$</pattern>`

---

### 7. nonEmptyField
Null/blank check for a single field.

```xml
<nonEmptyField customRejectMessage="Campaign_Name must not be null." description="" enabled="true" goal="NONEMPTY" inputField="Campaign_Name" name="Campaign_Name not null" outputField="" trimInput="false"/>
```

**`goal` values:** `NONEMPTY` (must have value), `EMPTY` (must be null/blank).

---

### 8. isNumber
Validates (and optionally converts) a string field to a numeric type.

```xml
<isNumber acceptEmpty="true" customRejectMessage="Amount must be a valid decimal." description="" enabled="true" inputField="Amount_Str" name="Amount is decimal" numberType="DECIMAL" outputField="Amount" trimInput="true">
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
</isNumber>
```

**`numberType` values:** `INTEGER`, `LONG`, `DECIMAL`, `NUMBER`

---

### 9. isDate
Validates (and optionally converts) a string field to a date type.

```xml
<isDate acceptEmpty="false" customRejectMessage="Invalid date. Expected yyyy-MM-dd." description="" enabled="true" inputField="Date_Str" name="Date_Str is valid date" outputField="Parsed_Date" trimInput="false">
    <languageSetting dateFormat="yyyy-MM-dd" locale="" numberFormat="" timezone="UTC"/>
</isDate>
```

---

### 10. transform
Full CTL2 transform function. Use when you need to compute/assign output fields with arbitrary logic.

```xml
<transform customRejectMessage="" description="" enabled="true" inputField="" name="Transform" outputField="">
    <transform><![CDATA[//#CTL2
function integer transform() {
    $out.0.Order_Date = $in.0.Order_Date;
    $out.0.Total = $in.0.Qty * $in.0.Price;
    return ALL;
}
]]></transform>
</transform>
```

CTL code goes in a `<transform>` child element containing a CDATA block with a full `transform()` function.

---

### 11. if / then / else
Conditional rule. Use for "if field A is set, then field B must also be set" patterns.

```xml
<if conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="Campaign integrity" statusCode="">
    <children>
        <nonEmptyField customRejectMessage="" description="" enabled="true" goal="NONEMPTY" inputField="Discount_Campaign" name="Discount_Campaign is set" outputField="" trimInput="false"/>
        <then conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="THEN" statusCode="">
            <children>
                <nonEmptyField customRejectMessage="Campaign start date required." description="" enabled="true" goal="NONEMPTY" inputField="Campaign_Start_Date" name="Campaign start required" outputField="" trimInput="false"/>
                <comparison acceptEmpty="false" customRejectMessage="Discount must be positive." description="" enabled="true" inputField="Discount_Pct" name="Discount positive" operator="GT" outputField="Discount_Pct" useType="DEFAULT" value="0">
                    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
                </comparison>
            </children>
            <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
            <imports/>
        </then>
        <else conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="ELSE" statusCode="">
            <children>
                <accept customRejectMessage="" description="" enabled="true" inputField="" name="Accept" outputField=""/>
            </children>
            <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
            <imports/>
        </else>
    </children>
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
    <imports/>
</if>
```

**Structure of `<if>`:** `<children>` contains: (1) condition rule(s), (2) `<then>` block, (3) `<else>` block.
Use `<accept/>` in `else` to pass records when the condition is false.

---

### 12. accept
Unconditionally passes the record. Used inside `else` branches.

```xml
<accept customRejectMessage="" description="" enabled="true" inputField="" name="Accept" outputField=""/>
```

---

### 13. group (nested)
Organizes rules into logical sub-groups.

```xml
<group conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="Price checks" statusCode="">
    <children>
        <comparison acceptEmpty="false" customRejectMessage="Price must be positive." description="" enabled="true" inputField="Price" name="Price positive" operator="GT" outputField="Price" useType="DEFAULT" value="0">
            <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
        </comparison>
    </children>
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
    <imports/>
</group>
```

---

### 14. customRules (inline CTL functions)
Define reusable CTL2 boolean functions inside the rule tree. Place `<customRules>` between `<languageSetting>` and `<imports/>`.

```xml
<group conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="false" name="All rules" statusCode="">
    <children>
        <copyAllByName customRejectMessage="" description="" enabled="true" inputField="" name="Copy all fields by name" outputField=""/>
    </children>
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
    <customRules>
        <customRule name="isValidEmail"><![CDATA[//#CTL2
function boolean isValidEmail(string email) {
    $out.0.validationMessage = "Invalid email: " + email;
    return !isnull(email) && containsMatch(email, ".+@.+\\..+");
}
]]></customRule>
    </customRules>
    <imports/>
</group>
```

**Importing CTL from external file** (alternative):
```xml
<imports>
    <import fileURL="${TRANS_DIR}/myRules.ctl"/>
</imports>
```

---

## COMPLETE WORKING EXAMPLE (with errorMapping + Denormalizer)

```xml
<!-- Metadata: shared by all three edges (valid, invalid, denormalizer output).
     rejectReason and recordNo are empty for valid records. -->
<Metadata id="MetaOrder">
<Record fieldDelimiter="," name="Order" previewAttachmentCharset="UTF-8" quoteChar="&quot;" quotedStrings="true" recordDelimiter="\n" type="delimited">
    <Field name="Order_Id" type="long"/>
    <Field name="Unit_Price" type="decimal"/>
    <Field name="Store_Country" type="string"/>
    <!-- ... other business fields ... -->
    <Field name="rejectReason" type="string"/>
    <Field name="recordNo" type="long"/>
</Record>
</Metadata>

<!-- VALIDATOR with errorMapping -->
<Node guiName="OrderValidator" guiX="400" guiY="300" id="ORDER_VALIDATOR" type="VALIDATOR">
    <attr name="rules"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<group conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="false" name="All order rules" statusCode="">
    <children>
        <copyAllByName customRejectMessage="" description="" enabled="true" inputField="" name="Copy all fields by name" outputField=""/>
        <group conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="Order identity" statusCode="">
            <children>
                <comparison acceptEmpty="false" customRejectMessage="Order_Id must be >= 0." description="" enabled="true" inputField="Order_Id" name="Order_Id non-negative" operator="GE" outputField="Order_Id" useType="DEFAULT" value="0">
                    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
                </comparison>
            </children>
            <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
            <imports/>
        </group>
        <group conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="Quantities and prices" statusCode="">
            <children>
                <interval acceptEmpty="false" boundaries="CLOSED_CLOSED" customRejectMessage="Unit_Quantity must be 1-9." description="" enabled="true" from="1" inputField="Unit_Quantity" name="Unit_Quantity [1,9]" outputField="Unit_Quantity" to="9" useType="DEFAULT">
                    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
                </interval>
                <interval acceptEmpty="false" boundaries="OPEN_CLOSED" customRejectMessage="Unit_Price must be greater than 10." description="" enabled="true" from="10" inputField="Unit_Price" name="Unit_Price > 10" outputField="Unit_Price" to="999999999.99" useType="DEFAULT">
                    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
                </interval>
                <comparison acceptEmpty="false" customRejectMessage="Total_Price must be non-negative." description="" enabled="true" inputField="Total_Price" name="Total_Price non-negative" operator="GE" outputField="Total_Price" useType="DEFAULT" value="0">
                    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
                </comparison>
                <expression description="" enabled="true" inputField="Total_Price" name="Total_Price must equal Qty * Price - Discount" outputField="">
                    <expression><![CDATA[isnull($in.0.Total_Price) || isnull($in.0.Unit_Quantity) || isnull($in.0.Unit_Price) || (abs($in.0.Total_Price - ($in.0.Unit_Quantity * $in.0.Unit_Price - (isnull($in.0.Total_Discount) ? 0 : $in.0.Total_Discount))) <= 0.02)]]></expression>
                </expression>
            </children>
            <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
            <imports/>
        </group>
        <group conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="Store" statusCode="">
            <children>
                <stringLength acceptEmpty="false" customRejectMessage="Store_Name must not be blank." description="" enabled="true" inputField="Store_Name" max="200" min="1" name="Store_Name not blank" outputField="Store_Name" trimInput="true">
                    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
                </stringLength>
                <patternMatch acceptEmpty="false" customRejectMessage="Country must be USA." description="" enabled="true" ignoreCase="false" inputField="Country" name="Country is USA" outputField="Country" trimInput="false">
                    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
                    <pattern>USA</pattern>
                </patternMatch>
            </children>
            <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
            <imports/>
        </group>
        <group conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="Campaign" statusCode="">
            <children>
                <if conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="Campaign integrity" statusCode="">
                    <children>
                        <nonEmptyField customRejectMessage="" description="" enabled="true" goal="NONEMPTY" inputField="Campaign_Name" name="Campaign set" outputField="" trimInput="false"/>
                        <then conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="THEN" statusCode="">
                            <children>
                                <comparison acceptEmpty="false" customRejectMessage="Discount must be > 0 when campaign is set." description="" enabled="true" inputField="Discount" name="Discount positive" operator="GT" outputField="Discount" useType="DEFAULT" value="0">
                                    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
                                </comparison>
                                <expression description="" enabled="true" inputField="Campaign_Start" name="Campaign end must not be before start" outputField="">
                                    <expression><![CDATA[isnull($in.0.Campaign_Start) || isnull($in.0.Campaign_End) || $in.0.Campaign_Start <= $in.0.Campaign_End]]></expression>
                                </expression>
                            </children>
                            <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
                            <imports/>
                        </then>
                        <else conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="ELSE" statusCode="">
                            <children>
                                <accept customRejectMessage="" description="" enabled="true" inputField="" name="Accept" outputField=""/>
                            </children>
                            <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
                            <imports/>
                        </else>
                    </children>
                    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
                    <imports/>
                </if>
            </children>
            <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
            <imports/>
        </group>
    </children>
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
    <imports/>
</group>
]]></attr>
    <attr name="errorMapping"><![CDATA[//#CTL2

function integer transform() {
    $out.1.* = $in.0.*;
    $out.1.rejectReason = $in.1.validationMessage;
    $out.1.recordNo = $in.1.recordNo;
    return ALL;
}
]]></attr>
</Node>

<!-- Denormalizer: collapses multiple error records per input record into one -->
<Node guiName="Denormalizer" guiX="820" guiY="375" id="DENORMALIZER" key="recordNo(a)" type="DENORMALIZER">
    <attr name="denormalize"><![CDATA[//#CTL2
string[] reasons = [];

function integer append() {
    reasons.append($in.0.rejectReason);
    return OK;
}

function integer transform() {
    $out.0 = $in.0;
    $out.0.rejectReason = join("|", reasons);
    return OK;
}

function void clean() {
    clear(reasons);
}
]]></attr>
</Node>

<!-- Edges -->
<Edge fromNode="READER:0"          id="Edge0" inPort="Port 0 (in)"      metadata="MetaOrder" outPort="Port 0 (output)"  toNode="ORDER_VALIDATOR:0"/>
<Edge fromNode="ORDER_VALIDATOR:0" id="Edge1" inPort="Port 0 (in)"      metadata="MetaOrder" outPort="Port 0 (valid)"   toNode="VALID_WRITER:0"/>
<Edge fromNode="ORDER_VALIDATOR:1" id="Edge2" inPort="Port 0 (in)"      metadata="MetaOrder" outPort="Port 1 (invalid)" toNode="DENORMALIZER:0"/>
<Edge fromNode="DENORMALIZER:0"    id="Edge3" inPort="Port 0 (in)"      metadata="MetaOrder" outPort="Port 0 (out)"     toNode="REJECTED_WRITER:0"/>
```

---

## VALID XML CHILD ELEMENTS (confirmed schema, CloverDX 7.3.x)

Accepted as children of `<group>` / `<children>`:

`group`, `if`, `then`, `else`, `enumMatch`, `nonEmptyField`, `nonEmptySubset`, `expression`, `patternMatch`, `stringLength`, `interval`, `comparison`, `isDate`, `isNumber`, `lookup`, `custom`, `email`, `phoneNumber`, `copy`, `transform`, `copyAllByName`, `external`, `accept`, `reject`

---

## UNCONFIRMED / POTENTIALLY WRONG RULE FORMS

Do not use without testing in CloverDX 7.3.x:

| Rule | Issue |
|---|---|
| `<enumMatch acceptValues="A,B" .../>` | `acceptValues` attribute rejected by schema validator |
| `<customRule name="fn" parameterMapping="p:=Field"/>` | `parameterMapping` attribute rejected by schema validator |
| `<lookup actionOnMatch="ACCEPT" keyMapping="..." lookupName="..."/>` | Untested — may require LookupTable declaration in `<Global>` |

**Safe alternative to `enumMatch`:** use `<patternMatch>` with `<pattern>^(A|B|C)$</pattern>`.
**Safe alternative to external `customRule`:** use `<expression>` with inline CDATA boolean expression.

---

## COMPLETE MISTAKES REFERENCE

| Mistake | Correct form |
|---|---|
| `expression="$in.0.x > 0"` as XML attribute | `<expression>` child element with CDATA |
| `return` or `//#CTL2` in `<expression>` child | Bare boolean only — no header, no return |
| `minLength`/`maxLength` on stringLength | Use `min` and `max` |
| `inputField2` or `referenceField` on comparison | comparison is constant-only; use `expression` for cross-field |
| `<code>` child on expression | Use `<expression>` child, not `<code>` |
| `acceptEmpty` attribute on expression | Not valid on `expression` element |
| `customRejectMessage` on `<expression>` element | **Not valid** — schema rejects it; use descriptive `name` attribute instead |
| `parameterMapping` on customRule | Not valid in 7.3.x |
| Omitting `inputField` from expression | Required even for multi-field expressions |
| `<languageSetting>` after `<expression>` child | expression has no siblings after its text node |
| operator `"E"` on comparison | Use `"EQ"` |
| operators `"GTE"` or `"LTE"` | Use `"GE"` or `"LE"` |
| XML comments inside CDATA rules block | Stripped by visual editor — use `name` attribute instead |
| Blank lines between rule elements | Stripped by visual editor — keep elements contiguous |
| Multi-line attribute formatting | Visual editor collapses to single line |
| Reformat/Map downstream re-implementing validation logic to generate rejection messages | **Wrong pattern** — use `errorMapping` on the VALIDATOR to capture `$in.1.validationMessage` directly |
| Connecting VALIDATOR invalid port directly to a writer with no reason | Missing `errorMapping` attribute — rejected records will have no explanation |
| Forgetting `clean()` in Denormalizer | Reasons list bleeds across record groups — produces corrupt concatenated output |

---

## EDGE DECLARATIONS FOR VALIDATOR (simple, no rejection reasons)

If rejection reasons are not required, connect port 1 directly to a writer:

```xml
<Edge fromNode="READER:0"       id="Edge0" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 0 (output)"  toNode="MY_VALIDATOR:0"/>
<Edge fromNode="MY_VALIDATOR:0" id="Edge1" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 0 (valid)"   toNode="VALID_WRITER:0"/>
<Edge fromNode="MY_VALIDATOR:1" id="Edge2" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 1 (invalid)" toNode="REJECT_WRITER:0"/>
```

For the full pattern with rejection reasons, see the **SURFACING REJECTION REASONS** section above.
