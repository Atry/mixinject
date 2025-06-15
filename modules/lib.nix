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
            else if selfName == lexicalVariableName then
              self
            else if outerSymbolTable != null then
              lookUpVariable outerSymbolTable lexicalVariableName
            else
              throw "Variable ${lexicalVariableName} is not found"
          );

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
                # An inheritance is a list of strings
                isInheritance = ast != [ ] && builtins.all builtins.isString ast;
              in
              if isInheritance then
                {
                  inheritances =
                    let
                      lexicalVariableName = builtins.head ast;
                      restSegments = builtins.tail ast;
                      lexicalVariable = lookUpVariable outerSymbolTable lexicalVariableName;
                      evaluation = builtins.foldl' (evaluation: segment: evaluation.allProperties.${segment}) lexicalVariable restSegments;
                    in
                    evaluation.ownMixins;

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


  systems = import inputs.systems;

  partitionedAttrs.checks = "dev";
  partitionedAttrs.packages = "dev";
  partitionedAttrs.devShells = "dev";
  partitions.dev = {
    extraInputsFlake = ../dev;
    extraInputs.devenv-root = inputs.devenv-root;
    module =
      { inputs
      , config
      , ...
      }: {
        imports = [
          inputs.nix-ml-ops.flakeModules.nixIde
          inputs.nix-ml-ops.flakeModules.nixLd
          inputs.nix-ml-ops.flakeModules.ldFallbackManylinux
          inputs.nix-ml-ops.flakeModules.devcontainerNix
        ];
        perSystem = { system, pkgs, ... }: {
          packages.update-tests-snapshot =
            let
              nixago = inputs.nix-ml-ops.inputs.nixago;
              evaluation = (config.flake.lib.evaluate [
                (config.flake.lib.compileDirectory rec {
                  directory = ../tests;

                  # Replace the hashed path with a relative path
                  pathMapping = path:
                    builtins.replaceStrings [ (toString directory) ] [ "tests" ] (toString path);

                })
              ]);
              snapshot = evaluation: {
                ownMixinKeys = builtins.map (mixin: mixin.key) evaluation.ownMixins;
                allMixinKeys = builtins.map (mixin: mixin.key) evaluation.allMixins;
                ${ if evaluation.allPrimitives == [ ] then null else "allPrimitives"} =
                  evaluation.allPrimitives;
                ${ if evaluation.allProperties == { } then null else "allPropertySnapshots"} =
                  builtins.mapAttrs (propertyName: snapshot) evaluation.allProperties;
              };
            in
            (nixago.lib.${system}.make {
              data = snapshot evaluation;
              output = "tests/snapshot.json";
              hook.mode = "copy";
            }).install;
        };
      };
  };
}
