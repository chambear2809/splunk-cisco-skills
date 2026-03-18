define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/StreamConfig/ContentExtractionTemplate.html",
    "app-js/models/Field"
], function(
    $,
    _,
    Backbone,
    ContentExtractionTemplate,
    Field
    ) {
    return Backbone.View.extend({

        className: 'modal',

        initialize: function(options) {

            this.options     = _.extend({}, this.options, options);
            this.template    = _.template($(ContentExtractionTemplate).html());
            this.app         = this.options.app;
            this.model       = this.options.model;
            this.streamModel = this.options.streamModel;
            this.stringTerms  = this.options.stringTerms;
            this.originalTerm = this.options.originalTerm;
            this.fieldsCollection = this.options.fieldsCollection;
            this.idleFieldsCollection = this.options.idleCollection;

            var self = this;

            this.listOfStringTerms = this.fieldsCollection.filter(function (field) {
                                            var isExtractedField = field.get('transformation')
                                            //only string terms from non-extracted fields can be extracted.
                                            return (field.get('term') in self.stringTerms) && !isExtractedField;
                                        }).map(function (field) {
                                            return {
                                                name: field.get('name'),
                                                term: field.get('term')
                                            }
                                        });

        },

        events: {
            'click .save'                        : 'save',
            'click .cancel'                      : 'cancel',
            'click #extraction-match-btn-group'  : 'toggleMatching',
            'click #extraction-hash-btn-group'   : 'toggleHashExtracted',
            'change #extraction-type'            : 'toggleExtractionType'
        },

        toggleMatching: function(e) {
            var btnGroup = e.target.parentElement;

            if (! $(e.target).hasClass('active'))
                $(btnGroup).find('.btn').toggleClass('active');
        },
                                
        toggleHashExtracted: function(e) {
            var btnGroup = e.target.parentElement;

            if (! $(e.target).hasClass('active'))
                $(btnGroup).find('.btn').toggleClass('active');
        },

        toggleExtractionType: function(e) {
            var type = e.target;
            switch (type.value) {
                case "regex":
                    $('.md5-hash-ctl').hide();
                    $('.sha512-hash-ctl').hide();
                    $('.regex-ctl').show();
                break;
                case "md5_hash":
                    $('.md5-hash-ctl').show();
                    $('.sha512-hash-ctl').hide();
                    $('.regex-ctl').hide();
                break;
                case "sha512_hash":
                    $('.md5-hash-ctl').hide();
                    $('.sha512-hash-ctl').show();
                    $('.regex-ctl').hide();
                break;
                case "hex":
                    $('.regex-ctl').hide();
                    $('.md5-hash-ctl').hide();
                    $('.sha512-hash-ctl').hide();
                break;
                default:
                    console.log("unexpected extraction type:" + type.value);
                break;
            }
        },

        cancel: function() {
            this.remove();
        },

        show: function() {

            var thisExtraction;
            if (this.options.fieldName) {
                thisExtraction = this.model.toJSON();
            }

            this.$el.html(this.template({
                originalTerm      : this.originalTerm,
                listOfStringTerms : this.listOfStringTerms,
                extraction        : thisExtraction || null,
                isAggregated      : this.streamModel.get("aggregated")
            }));

            this.$el.on('hide', function() {
                this.remove();
            }.bind(this));

            this.$el.modal('show');
            return this;

        },

        save: function(e) {

            e.preventDefault();
            var self = this;
            //Get the user inputs
            var originTerm            = $("#origin-term").val();
            var extractionType        = $("#extraction-type").val();
            var extractionRule        = $("#extraction-rule").val();
            var extractionFormat      = $("#extraction-format").val();
            var extractionName        = $("#extraction-name").val();
            var extractionDescription = $("#extraction-description").val() || "";
            var isList                = false;
            var extractionHashLength  = $("#extraction-hash-length").val();
            var extractionHashOffset  = $("#extraction-hash-offset").val();
            var extractionHashSalt    = $("#extract-sha-512-hash-salt").val();

            if (extractionType == "md5_hash") {
                extractionHashLength = $("#md5-extraction-hash-length").val();
                extractionHashOffset = $("#md5-extraction-hash-offset").val();
                extractionHashSalt    = $("#md5-extraction-hash-salt").val();
            } else if (extractionType == "sha512_hash") {
                extractionHashLength = $("#sha512-extraction-hash-length").val();
                extractionHashOffset = $("#sha512-extraction-hash-offset").val();
                extractionHashSalt    = $("#sha512-extraction-hash-salt").val();
            }

            var isAggregated = self.streamModel.get("aggregated");
            var transformation = { type: extractionType };
            
            // Assign the relevant parts of the transformation based on its extractionType.
            if (extractionType == "regex") {
                transformation.value = extractionRule;
                transformation.format = extractionFormat;
                isList = $("#ce-match-all").is(".active");
                transformation.hashExtracted = $("#ce-hash-yes").is(".active");
                if (transformation.hashExtracted) {
                    if (!isNaN(parseInt(extractionHashLength)))
                        transformation.hashExtractedLength = parseInt(extractionHashLength);
                    if (!isNaN(parseInt(extractionHashOffset)))
                        transformation.hashExtractedOffset = parseInt(extractionHashOffset);
                    transformation.hashExtractedSalt = extractionHashSalt;
                }
            } else if (extractionType == "md5_hash" || extractionType == "sha512_hash") {
                if (!isNaN(parseInt(extractionHashLength)))
                    transformation.hashLen = parseInt(extractionHashLength);
                if (!isNaN(parseInt(extractionHashOffset)))
                    transformation.hashOffset = parseInt(extractionHashOffset);
                transformation.hashSalt = extractionHashSalt;

                var selectedField = this.fieldsCollection.find(function(field) { return field.get("term") == originTerm; });
                isList = (selectedField != null) && (selectedField.get("isList") == true);
            } else if (extractionType == "hex") {
                var selectedField = this.fieldsCollection.find(function(field) { return field.get("term") == originTerm; });
                isList = (selectedField != null) && (selectedField.get("isList") == true);
            }

            var newExtractionField = {
                enabled : true,
                //default is "value", unless stream is agg_event, then "key"
                aggType : isAggregated ? "key" : "value",
                desc    : extractionDescription,
                term    : originTerm,
                name    : extractionName,
                isList  : isList,
                transformation: transformation
            };

            var fields = self.streamModel.get("fields") || [];

            var isEditingExtraction = !!self.options.fieldName;

            /*==========  If editing extraction  ==========*/

            if (isEditingExtraction) {
                // ((name-not-changed OR name-is-unique) AND values-filled)
                if ((newExtractionField.name === self.options.fieldName ||
                    !isDuplicateFieldName(fields, newExtractionField.name)) &&
                    valuesFilledAndValid())
                {
                    newExtractionField.enabled = this.model.get('enabled');
                    newExtractionField.aggType = this.model.get('aggType');

                    //pseudo edit, delete and create.
                    self.fieldsCollection.remove(this.model);
                    self.fieldsCollection.add(new Field(newExtractionField));

                    //find same field in the non-active fields collection to remove and replace
                    var idleModel = self.idleFieldsCollection.findWhere({name: self.options.fieldName});
                    self.idleFieldsCollection.remove(idleModel);
                    newExtractionField.aggType = isAggregated ? "value" : "key";
                    self.idleFieldsCollection.add(new Field(newExtractionField));

                    self.$el.modal('hide');
                    self.remove();
                } else {
                    //do nothing
                }
            }

            /*==========  If creating new extraction  ==========*/

            else {
                // (name-unique AND values-filled)
                if (!isDuplicateFieldName(fields, newExtractionField.name) && valuesFilledAndValid()) {
                    //add new field to both agg and non-agg field collections
                    self.fieldsCollection.add(new Field(newExtractionField));
                    newExtractionField.aggType = isAggregated ? "value" : "key";
                    self.idleFieldsCollection.add(new Field(newExtractionField))

                    self.$el.modal('hide');
                    self.remove();
                } else {
                    //do nothing
                }
            }

            /*=========================================
            =            Utility Functions            =
            =========================================*/

            //TODO: use field model w/ validation?

            function valuesFilledAndValid() {
                var errors = [];

                if (!extractionName) {
                    errors.push("Name is required.");
                }
                if (!extractionDescription) {
                    errors.push("Description is required.");
                }
                if (extractionType == "regex" && !extractionRule) {
                    errors.push("Extraction Rule is required.");
                }
                if (extractionName && !extractionName.match(/^\w+$/)){
                    errors.push("Please specify a name using only letters, digits and underscores ('_').");
                }
                if (extractionType == "regex") {
                    if (!regexIsValid(extractionRule)) {
                        errors.push("Invalid regex expression.");
                    }
                    if (extractionHashOffset.length &&
                        ( isNaN(parseInt(extractionHashOffset)) || parseInt(extractionHashOffset) < 0 || parseInt(extractionHashOffset) > 63)) {
                        errors.push("Hash Offset must be an integer between 0 and 63");
                    } else if (extractionHashLength.length &&
                        (isNaN(parseInt(extractionHashLength)) || parseInt(extractionHashLength) < 1 || parseInt(extractionHashLength) > 64)) {
                        errors.push("Hash Length must be an integer between 1 and 64");
                    } else if (parseInt(extractionHashOffset) + parseInt(extractionHashLength) > 64) {
                        errors.push("Invalid combination of Hash Offset and Hash Length fields.");
                    } else if (extractionHashSalt.length && extractionHashSalt.length > 32 ) {
                        errors.push("Hash Salt cannot not be more than 32 chars");
                    }
                }
                if (extractionType == "md5_hash") {

                    if (extractionHashOffset.length &&
                        ( isNaN(parseInt(extractionHashOffset)) || parseInt(extractionHashOffset) < 0 || parseInt(extractionHashOffset) > 31)) {
                        errors.push("Hash Offset must be an integer between 0 and 31");
                    } else if (extractionHashLength.length &&
                        (isNaN(parseInt(extractionHashLength)) || parseInt(extractionHashLength) < 1 || parseInt(extractionHashLength) > 32)) {
                        errors.push("Hash Length must be an integer between 1 and 32");
                    } else if (parseInt(extractionHashOffset) + parseInt(extractionHashLength) > 32) {
                        errors.push("Invlid combination of Hash Offset and Hash Length fields.");
                    } else if (extractionHashSalt.length && extractionHashSalt.length > 32 ) {
                        errors.push("Hash Salt cannot not be more than 32 chars");
                    }
                }

                if (extractionType == "sha512_hash") {

                    if (extractionHashOffset.length &&
                        ( isNaN(parseInt(extractionHashOffset)) || parseInt(extractionHashOffset) < 0 || parseInt(extractionHashOffset) > 63)) {
                        errors.push("Hash Offset must be an integer between 0 and 63");
                    } else if (extractionHashLength.length &&
                        (isNaN(parseInt(extractionHashLength)) || parseInt(extractionHashLength) < 1 || parseInt(extractionHashLength) > 64)) {
                        errors.push("Hash Length must be an integer between 1 and 64");
                    } else if (parseInt(extractionHashOffset) + parseInt(extractionHashLength) > 64) {
                        errors.push("Invlid combination of Hash Offset and Hash Length fields.");
                    } else if (extractionHashSalt.length && extractionHashSalt.length > 32 ) {
                        errors.push("Hash Salt cannot not be more than 32 chars");
                    }
                }

                if (errors.length > 0) {
                    var alertMessage = "";
                    for (var i = 0; i < errors.length; i++) {
                        alertMessage += "\n\u2022 " + errors[i];
                    };
                    alert(alertMessage);
                    return false;
                } else {
                    return true;
                }

                function regexIsValid(regex) {
                    var isValid;
                    try {
                        new RegExp(regex);
                        isValid = true;
                    }
                    catch(e) {
                        isValid = false;
                    }
                    return isValid;
                }
            }

            function isDuplicateFieldName(fields, name){
                var isDuplicate = _.some(fields, function(each) {
                    return (each.name === name);
                });
                if (isDuplicate) {
                    alert("Duplicate name.")
                    return true;
                }
                else {
                    return false;
                }

            }

        }

    });
});
