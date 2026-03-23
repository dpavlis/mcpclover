# CloverDX VALIDATOR — LLM Reference (7.3.x)

## VISUAL EDITOR RULES (follow strictly to avoid reformat warnings)

- No XML comments inside the rules CDATA block — use `name` / `customRejectMessage` attributes instead
- No blank lines between elements
- All attributes on one line (no multi-line formatting)
- Attributes in alphabetical order: `acceptEmpty` → `boundaries` → `customRejectMessage` → `description` → `enabled` → `from` → `inputField` → `name` → `operator` → `outputField` → `to` → `trimInput` → `useType` → `value`
- `<expression>` CTL content wrapped in `<![CDATA[...]]>` child element; inside CDATA write operators literally (`<=`, `>=`, `&&`) — no XML escaping
- Every `<group>`, `<if>`, `<then>`, `<else>` child order: `<children>` → `<languageSetting/>` → `<customRules>` (if needed) → `<imports/>`

## SKELETON

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

- Port 0 `Port 0 (valid)`, port 1 `Port 1 (invalid)`

## ROOT GROUP ATTRIBUTES

| Attr | Values | Notes |
|---|---|---|
| `conjunction` | `AND` / `OR` | AND = all rules pass; OR = any rule passes |
| `lazyEvaluation` | `true` / `false` | true = stop at first failure; false = evaluate all |
| `errorMessageProducer` | `RULES` / `GROUP` | RULES = each rule emits its own message |

## REJECTION REASON PATTERN (errorMapping + Denormalizer)

**Never re-implement validation logic downstream to generate rejection messages.** Use `errorMapping` — a CTL2 transform fired per failing rule that receives `$in.0` (rejected record) and `$in.1` (error info: `validationMessage`, `recordNo`).

Root group `lazyEvaluation="false"` + sub-groups `lazyEvaluation="true"` → one error per failing sub-group → one input record can produce multiple error records → use Denormalizer to collapse. If root `lazyEvaluation="true"`, at most one error per record (Denormalizer optional but harmless).

**Step 1 — add to shared metadata (used on all three edges):**
```xml
<Field name="rejectReason" type="string"/>
<Field name="recordNo" type="long"/>
```

**Step 2 — add `errorMapping` to VALIDATOR:**
```xml
<attr name="errorMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.* = $in.0.*;
    $out.1.rejectReason = $in.1.validationMessage;
    $out.1.recordNo = $in.1.recordNo;
    return ALL;
}
]]></attr>
```

**Step 3 — Denormalizer to collapse multiple errors per record:**
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
`clean()` is **required** — without it reasons bleed across groups.

**Edges (with rejection reasons):**
```xml
<Edge fromNode="READER:0"       id="Edge0" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 0 (output)"  toNode="MY_VALIDATOR:0"/>
<Edge fromNode="MY_VALIDATOR:0" id="Edge1" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 0 (valid)"   toNode="VALID_WRITER:0"/>
<Edge fromNode="MY_VALIDATOR:1" id="Edge2" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 1 (invalid)" toNode="DENORMALIZER:0"/>
<Edge fromNode="DENORMALIZER:0" id="Edge3" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 0 (out)"     toNode="REJECTED_WRITER:0"/>
```

**Edges (simple, no rejection reasons):**
```xml
<Edge fromNode="READER:0"       id="Edge0" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 0 (output)"  toNode="MY_VALIDATOR:0"/>
<Edge fromNode="MY_VALIDATOR:0" id="Edge1" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 0 (valid)"   toNode="VALID_WRITER:0"/>
<Edge fromNode="MY_VALIDATOR:1" id="Edge2" inPort="Port 0 (in)"      metadata="MetaMyRecord" outPort="Port 1 (invalid)" toNode="REJECT_WRITER:0"/>
```

## RULE REFERENCE

### copyAllByName — always place first
```xml
<copyAllByName customRejectMessage="" description="" enabled="true" inputField="" name="Copy all fields by name" outputField=""/>
```

### comparison — field vs constant
```xml
<comparison acceptEmpty="false" customRejectMessage="Order_Id must be >= 0." description="" enabled="true" inputField="Order_Id" name="Order_Id non-negative" operator="GE" outputField="Order_Id" useType="DEFAULT" value="0">
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
</comparison>
```
Operators: `GE` `GT` `LE` `LT` `EQ` `NE`. Cross-field comparisons → use `expression`. Wrong: `E` (use `EQ`), `GTE`/`LTE` (use `GE`/`LE`).

### interval — range check
```xml
<interval acceptEmpty="false" boundaries="CLOSED_CLOSED" customRejectMessage="Year must be in [1990, 2030]." description="" enabled="true" from="1990" inputField="Year" name="Year range" outputField="Year" to="2030" useType="DEFAULT">
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
</interval>
```
`boundaries`: `CLOSED_CLOSED` (<=x<=), `OPEN_CLOSED` (<x<=), `CLOSED_OPEN` (<=x<), `OPEN_OPEN` (<x<). For dates set `languageSetting dateFormat="yyyy-MM-dd" timezone="UTC"` and use ISO strings in `from`/`to`.

### expression — CTL2 boolean, cross-field logic
```xml
<expression description="" enabled="true" inputField="Start_Date" name="Start date must not be after end date" outputField="">
    <expression><![CDATA[isnull($in.0.Start_Date) || isnull($in.0.End_Date) || $in.0.Start_Date <= $in.0.End_Date]]></expression>
</expression>
```
- `inputField` required even for multi-field expressions
- Child `<expression>` CDATA: bare boolean only — no `return`, no `//#CTL2`
- No `<languageSetting>` after the child element
- **`customRejectMessage` NOT valid on `<expression>`** — schema rejects it; use descriptive `name` instead

### stringLength — length + null check
```xml
<stringLength acceptEmpty="false" customRejectMessage="Store_Name must not be blank." description="" enabled="true" inputField="Store_Name" max="200" min="1" name="Store_Name not blank" outputField="Store_Name" trimInput="true">
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
</stringLength>
```
Attributes are `min`/`max` — NOT `minLength`/`maxLength`.

### patternMatch — Java regex
```xml
<patternMatch acceptEmpty="false" customRejectMessage="Country must be USA." description="" enabled="true" ignoreCase="false" inputField="Store_Country" name="Store_Country is USA" outputField="Store_Country" trimInput="false">
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
    <pattern>USA</pattern>
</patternMatch>
```
Pattern in `<pattern>` child element. Enum-style: `<pattern>^(USA|CAN|MEX)$</pattern>`.

### nonEmptyField — null/blank check
```xml
<nonEmptyField customRejectMessage="Campaign_Name must not be null." description="" enabled="true" goal="NONEMPTY" inputField="Campaign_Name" name="Campaign_Name not null" outputField="" trimInput="false"/>
```
`goal`: `NONEMPTY` (must have value) or `EMPTY` (must be null/blank).

### isNumber — string → numeric validation/conversion
```xml
<isNumber acceptEmpty="true" customRejectMessage="Amount must be a valid decimal." description="" enabled="true" inputField="Amount_Str" name="Amount is decimal" numberType="DECIMAL" outputField="Amount" trimInput="true">
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
</isNumber>
```
`numberType`: `INTEGER` `LONG` `DECIMAL` `NUMBER`.

### isDate — string → date validation/conversion
```xml
<isDate acceptEmpty="false" customRejectMessage="Invalid date. Expected yyyy-MM-dd." description="" enabled="true" inputField="Date_Str" name="Date_Str is valid date" outputField="Parsed_Date" trimInput="false">
    <languageSetting dateFormat="yyyy-MM-dd" locale="" numberFormat="" timezone="UTC"/>
</isDate>
```

### transform — full CTL2 transform
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

### if / then / else — conditional rule
```xml
<if conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="Campaign integrity" statusCode="">
    <children>
        <nonEmptyField customRejectMessage="" description="" enabled="true" goal="NONEMPTY" inputField="Campaign_Name" name="Campaign set" outputField="" trimInput="false"/>
        <then conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="THEN" statusCode="">
            <children>
                <comparison acceptEmpty="false" customRejectMessage="Discount must be > 0 when campaign is set." description="" enabled="true" inputField="Discount" name="Discount positive" operator="GT" outputField="Discount" useType="DEFAULT" value="0">
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
`<if>` children order: condition rule(s), then `<then>`, then `<else>`. Use `<accept/>` in `<else>` to pass records when condition is false.

### accept — unconditional pass (use in else branches)
```xml
<accept customRejectMessage="" description="" enabled="true" inputField="" name="Accept" outputField=""/>
```

### group — nested sub-group
```xml
<group conjunction="AND" description="" enabled="true" errorMessage="" errorMessageProducer="RULES" lazyEvaluation="true" name="Price checks" statusCode="">
    <children>
        <!-- rules here -->
    </children>
    <languageSetting dateFormat="" locale="" numberFormat="" timezone=""/>
    <imports/>
</group>
```

### customRules — inline CTL helper functions
Place `<customRules>` between `<languageSetting>` and `<imports/>`:
```xml
<customRules>
    <customRule name="isValidEmail"><![CDATA[//#CTL2
function boolean isValidEmail(string email) {
    return !isnull(email) && containsMatch(email, ".+@.+\\..+");
}
]]></customRule>
</customRules>
```
External CTL file alternative: `<imports><import fileURL="${TRANS_DIR}/myRules.ctl"/></imports>`

## VALID CHILD ELEMENTS

Accepted in `<group>` / `<children>`: `group`, `if`, `then`, `else`, `enumMatch`, `nonEmptyField`, `nonEmptySubset`, `expression`, `patternMatch`, `stringLength`, `interval`, `comparison`, `isDate`, `isNumber`, `lookup`, `custom`, `email`, `phoneNumber`, `copy`, `transform`, `copyAllByName`, `external`, `accept`, `reject`

## UNCONFIRMED / POTENTIALLY WRONG

| Rule | Issue |
|---|---|
| `<enumMatch acceptValues="A,B" .../>` | `acceptValues` rejected by schema — use `<patternMatch>` with `<pattern>^(A|B)$</pattern>` instead |
| `<customRule name="fn" parameterMapping="p:=Field"/>` | `parameterMapping` rejected by schema — use `<expression>` with inline CDATA instead |
| `<lookup actionOnMatch="ACCEPT" .../>` | Untested — may require `<LookupTable>` in `<Global>` |

## MISTAKES

| Wrong | Correct |
|---|---|
| `expression="$in.0.x > 0"` as XML attribute | `<expression>` child element with CDATA |
| `return` or `//#CTL2` in `<expression>` child | Bare boolean only |
| `minLength`/`maxLength` on stringLength | `min` and `max` |
| `inputField2` or `referenceField` on comparison | comparison is constant-only; use `expression` for cross-field |
| `<code>` child on expression | `<expression>` child, not `<code>` |
| `acceptEmpty` on expression element | Not valid |
| `customRejectMessage` on `<expression>` element | Not valid — schema rejects it; use descriptive `name` instead |
| `parameterMapping` on customRule | Not valid in 7.3.x |
| Omitting `inputField` from expression | Required even for multi-field expressions |
| `<languageSetting>` after `<expression>` child | expression has no siblings after its text node |
| operator `"E"` | Use `"EQ"` |
| operators `"GTE"` or `"LTE"` | Use `"GE"` or `"LE"` |
| XML comments inside rules CDATA | Stripped by visual editor — use `name` instead |
| Blank lines between rule elements | Visual editor strips them |
| Multi-line attribute formatting | Visual editor collapses to single line |
| Downstream Reformat re-implementing rejection messages | Use `errorMapping` on VALIDATOR — captures `$in.1.validationMessage` directly |
| Port 1 connected with no `errorMapping` | Rejected records have no explanation |
| Omitting `clean()` in Denormalizer | Reasons list bleeds across groups |
