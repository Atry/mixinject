{ inputs, lib, ... }:
let
  uncurry = builtins.foldl' lib.id;
in
{
  imports = [
    inputs.flake-parts.flakeModules.partitions
  ];

  flake.lib =
    rec {
      /**
        # Type

        ```
        defaultImporters :: { ${extension} :: String -> Any }
        ```
      */
      defaultImporters = {
        json = lib.importJSON;
        toml = lib.importTOML;
        yaml = inputs.yaml.lib.fromYaml;
      };

      /**
        # Type

        ```
        lookUpVariable :: SymbolTable -> String -> Evaluation

        SymbolTable = {
          selfName :: String | null
          self :: Evaluation
          outerSymbolTable :: SymbolTable | null
          isOwnProperty :: String -> Boolean
        }

        Evaluation :: {
          ownMixins :: [ Mixin ]
          allMixins :: [ Mixin ]
          allPrimitives :: [ Any ]
          allProperties :: {
            ${name} :: Evaluation
          }
        }
        ```

      */
      lookUpVariable =
        { selfName
        , self
        , outerSymbolTable
        , isOwnProperty
        }: lexicalVariableName:
        builtins.addErrorContext
          "while looking up variable ${builtins.toJSON lexicalVariableName} in symbol table ${builtins.toJSON selfName}"
          (
            if isOwnProperty lexicalVariableName then
              self.allProperties.${lexicalVariableName}
            else if outerSymbolTable != null then
              lookUpVariable outerSymbolTable lexicalVariableName
            else
              throw "Variable ${lexicalVariableName} is not found"
          );

      /**
        # Type

        ```
        resolveQualifiedThis :: SymbolTable -> String -> Evaluation
        ```

        Resolves an explicit qualified this reference by walking the symbol table
        to find the scope whose selfName matches, and returns that scope's
        dynamic self (evaluation).
      */
      resolveQualifiedThis = symbolTable: qualifiedSelfName:
        let
          findQualifiedSelf = currentSymbolTable:
            if currentSymbolTable == null then
              throw "Qualified self name ${qualifiedSelfName} is not found"
            else if currentSymbolTable.selfName == qualifiedSelfName then
              currentSymbolTable.self
            else
              findQualifiedSelf currentSymbolTable.outerSymbolTable;
        in
        findQualifiedSelf symbolTable;

      /**

        # Type

        ```
        compileAst :: {
          ast :: Any
          key :: String
          sourceFile :: String
          position :: [ String ]
          outerSymbolTable :: SymbolTable
          selfName :: String
        } -> Mixin

        Mixin = {
          key :: String
          inheritances :: [ Mixin ]
          primitives :: [ Any ]
          ownProperties :: {
            ${name} :: Evaluation -> [ Mixin ]
          }
        }
        ```
      */
      compileAst =
        { sourceFile
        , position
        , ast
        , outerSymbolTable
        , selfName
        }:
        let
          isOwnProperty = propertyName: mixin.ownProperties ? ${propertyName};
          collectDefinitions = ast: position:

            if builtins.isAttrs ast then
              let
                compileProperty = propertyName: propertyAst: {
                  propertyPosition = position ++ [ propertyName ];
                  __functor = { __functor, propertyPosition }: self: [
                    (compileAst {
                      ast = propertyAst;
                      inherit sourceFile;
                      position = propertyPosition;
                      outerSymbolTable = {
                        inherit isOwnProperty selfName self outerSymbolTable;
                      };
                      selfName = propertyName;
                    })
                  ];
                };
              in
              {
                inheritances = [ ];
                primitives = [ ];
                ownProperties = (builtins.mapAttrs compileProperty ast);
              }
            else if builtins.isList ast then
              let
                astLength = builtins.length ast;

                # Qualified this syntax: [SelfName, null, path, segments...]
                # In YAML, write [SelfName,, path, segments] or [SelfName, ~, path, segments].
                # Analogous to Java's Outer.this.path.segments.
                isNewQualifiedThis =
                  astLength >= 2
                  && builtins.isString (builtins.head ast)
                  && builtins.elemAt ast 1 == null
                  && builtins.all builtins.isString (lib.drop 2 ast);

                # Deprecated qualified this syntax: [SelfName, [path, segments]]
                # The path segments list can be empty, resolving to the self at that scope level.
                isExplicitQualifiedThis =
                  astLength == 2
                  && builtins.isString (builtins.head ast)
                  && builtins.isList (builtins.elemAt ast 1)
                  && builtins.all builtins.isString (builtins.elemAt ast 1);

                # An inheritance is a list of strings
                isInheritance = ast != [ ] && builtins.all builtins.isString ast;
              in
              if isNewQualifiedThis then
                let
                  qualifiedSelfName = builtins.head ast;
                  pathSegments = lib.drop 2 ast;
                  resolved = resolveQualifiedThis outerSymbolTable qualifiedSelfName;
                  evaluation = builtins.foldl' (evaluation: segment: evaluation.allProperties.${segment}) resolved pathSegments;
                in
                {
                  inheritances = evaluation.ownMixins;
                  primitives = [ ];
                  ownProperties = { };
                }
              else if isExplicitQualifiedThis then
                let
                  lexicalVariableName = builtins.head ast;
                  pathSegments = builtins.elemAt ast 1;
                  resolved = builtins.trace
                    "WARNING: Deprecated qualified this syntax [${lexicalVariableName}, [${builtins.concatStringsSep ", " pathSegments}]] in ${sourceFile}. Use [${lexicalVariableName},, ${builtins.concatStringsSep ", " pathSegments}] instead."
                    (resolveQualifiedThis outerSymbolTable lexicalVariableName);
                  evaluation = builtins.foldl' (evaluation: segment: evaluation.allProperties.${segment}) resolved pathSegments;
                in
                {
                  inheritances = evaluation.ownMixins;
                  primitives = [ ];
                  ownProperties = { };
                }
              else if isInheritance then
                let
                  lexicalVariableName = builtins.head ast;
                  pathSegments = builtins.tail ast;
                  resolved = lookUpVariable outerSymbolTable lexicalVariableName;
                  evaluation = builtins.foldl' (evaluation: segment: evaluation.allProperties.${segment}) resolved pathSegments;
                in
                {
                  inheritances = evaluation.ownMixins;
                  primitives = [ ];
                  ownProperties = { };
                }
              else
                let
                  collectArrayItemDefinitions = index: arrayItemAst:
                    collectDefinitions arrayItemAst (position ++ [ (toString index) ]);
                  unmergedDefinitions = lib.imap collectArrayItemDefinitions ast;
                in
                {
                  inheritances = lib.concatMap (definition: definition.inheritances) unmergedDefinitions;
                  primitives = lib.concatMap (definition: definition.primitives) unmergedDefinitions;
                  ownProperties =
                    let
                      /**
                      # Type

                      ```
                      constructors :: [ { ${name} :: Evaluation -> [ Mixin ] } ]
                      ```
                         */
                      unmergedOwnProperties = builtins.map (definition: definition.ownProperties) unmergedDefinitions;
                    in
                    (lib.zipAttrsWith (propertyName: mergeConstructors)) unmergedOwnProperties;
                }
            else
              {
                inheritances = [ ];
                primitives = [ ast ];
                ownProperties = { };
              };
          mixin = let definitions = collectDefinitions ast position; in {
            key = builtins.toJSON { inherit position sourceFile; };

            inherit (definitions) inheritances primitives ownProperties;
          };
        in
        mixin;

      /**
        # Type

        ```
        mergeConstructors :: (Evaluation -> [ Mixin ]) -> Evaluation -> [ Mixin ]
        ```
      */
      mergeConstructors = constructors: {
        __toString = "<merged mixin constructor: ${builtins.toString constructors}>";
        __functor = { __functor, __toString }: self:
          builtins.concatMap (constructor: constructor self) constructors;
      };


      /**
        # Type

        ```
        compileDirectory :: {
          directory: [ String ], 
          importers?: { ${extension} :: String -> Any }
          outerSymbolTable? :: SymbolTable
          selfName? :: String
        } -> Mixin
        ```
      */
      compileDirectory =
        { directory
        , importers ? defaultImporters
        , outerSymbolTable ? null
        , selfName ? null
        , pathMapping ? lib.id
        }:
        let
          isOwnProperty = propertyName: mixin.ownProperties ? ${propertyName};
          mixin =
            {
              key = toString (pathMapping directory);
              inheritances = [ ];
              primitives = [ ];
              ownProperties =
                let
                  tryCompileFileOrDirectory = fileName: type:
                    if type == "directory" then
                      let
                        subDirectory = directory + ("/" + fileName);
                      in
                      {
                        ${fileName} = self: [
                          (compileDirectory {
                            directory = subDirectory;
                            selfName = fileName;
                            outerSymbolTable = {
                              inherit selfName self outerSymbolTable isOwnProperty;
                            };
                            inherit pathMapping importers;
                          })
                        ];
                      }
                    else
                      let
                        match = builtins.match "^(.*)\\.mixin\\.([^./]+)$" fileName;
                        tryCompileFile = baseFileName: fileExtension:
                          if importers ? ${fileExtension} then
                            {
                              ${baseFileName} = {
                                realSourceFile = directory + ("/" + fileName);
                                __functor = { __functor, realSourceFile }: self: [
                                  (compileAst {
                                    outerSymbolTable = {
                                      inherit selfName self outerSymbolTable isOwnProperty;
                                    };
                                    selfName = baseFileName;
                                    ast = importers.${fileExtension} realSourceFile;
                                    sourceFile = pathMapping realSourceFile;
                                    position = [ ];
                                  })
                                ];
                              };
                            }
                          else
                            { };
                      in
                      if match == null then { } else uncurry tryCompileFile match;
                in
                lib.pipe directory [
                  builtins.readDir
                  (lib.mapAttrsToList tryCompileFileOrDirectory)
                  (lib.zipAttrsWith (propertyName: mergeConstructors))
                ];

            };
        in
        mixin;


      /**
        # Type

        ```
        evaluate :: [ Mixin ] -> Evaluation
        ```
      */
      evaluate = ownMixins:
        let
          self = rec {
            inherit ownMixins;
            allMixins = builtins.addErrorContext
              "while deduplicating inheritances ${builtins.toJSON (builtins.map (mixin: mixin.key) ownMixins)}"
              (
                builtins.genericClosure {
                  startSet = ownMixins;
                  operator = mixin: mixin.inheritances;
                }
              );
            allPrimitives = lib.concatMap (mixin: mixin.primitives) allMixins;
            allProperties = builtins.addErrorContext
              "while evaluating properties from mixins ${builtins.toJSON (builtins.map (mixin: mixin.key) ownMixins)}"
              (
                lib.pipe allMixins [
                  (builtins.map (mixin: mixin.ownProperties))
                  (builtins.zipAttrsWith
                    (propertieName: propertyConstructors:
                      evaluate (mergeConstructors propertyConstructors self)
                    )
                  )
                ]
              );
          };
        in
        self;

      assertTypeChecked = { allPrimitives, allProperties, ownMixins, ... }: next: builtins.addErrorContext
        "while type checking the mixins ${builtins.toJSON (builtins.map (mixin: mixin.key) ownMixins)}"
        (
          if allPrimitives == [ ] then
            let
              ownProperties = lib.pipe ownMixins [
                (builtins.map (mixin: mixin.ownProperties))
                (builtins.zipAttrsWith (propertieName: _propertyConstructors:
                  allProperties.${propertieName}
                ))
              ];
            in
            lib.pipe next (builtins.map assertTypeChecked (builtins.attrValues ownProperties))
          else if allProperties == { } then
            if builtins.length allPrimitives == 1 then
              next
            else
              throw "Mixins cannot have multiple primitives"
          else
            throw "Mixins cannot have both primitives and properties"
        );
    };

}
