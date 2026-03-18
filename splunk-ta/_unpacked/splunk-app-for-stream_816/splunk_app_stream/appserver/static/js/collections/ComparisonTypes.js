define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/ComparisonType"
], function(
    $,
    _,
    Backbone,
    ComparisonType
    ) {
    return Backbone.Collection.extend({

        model: ComparisonType,

    }, 
    
    //class level functions
    {

        comparisonTable: [

                {id: 'false', description:'False', arity: 1, categories: ['generic', 'numeric', 'string', 'date_time', 'date', 'time']},
                {id: 'true', description: 'True', arity: 1, categories: ['generic', 'numeric', 'string', 'date_time', 'date', 'time']},
                {id: 'is-defined', description: 'Is defined', arity: 1, categories: ['generic', 'numeric', 'string', 'date_time', 'date', 'time']},
                {id: 'is-not-defined', description: 'Is not defined', arity: 1, categories: ['generic', 'numeric', 'string', 'date_time', 'date', 'time']},
                {id: 'equals', description: 'Equals', arity: 2, categories: ['numeric']},
                {id: 'not-equals', description: 'Does not equal', arity: 2, categories: ['numeric']},
                {id: 'greater-than', description: 'Greater than', arity: 2, categories: ['numeric']},
                {id: 'less-than', description: 'Less than', arity: 2, categories: ['numeric']},
                {id: 'greater-or-equal', 'description': 'Greater than or equal to', arity: 2, categories: ['numeric']},
                {id: 'less-or-equal', description: 'Less than or equal to', arity: 2, categories: ['numeric']},
                {id: 'regex', description: 'Regular Expression', arity: 2, categories: ['string']},
                {id: 'not-regex', description: 'Not Regular Expression', arity: 2, categories: ['string']},
                {id: 'exact-match-primary', description: 'Exactly matches', arity: 2, categories: ['string']},
                {id: 'not-exact-match-primary', description: 'Does not exactly match', arity: 2, categories: ['string']},
                {id: 'contains-primary', description: 'Contains', arity: 2, categories: ['string']},
                {id: 'not-contains-primary', description: 'Does not contain', arity: 2, categories: ['string']},
                {id: 'starts-with-primary', description: 'Starts with', arity: 2, categories: ['string']},
                {id: 'not-starts-with-primary', description: 'Does not start with', arity: 2, categories: ['string']},
                {id: 'ends-with-primary', description: 'Ends with', arity: 2, categories: ['string']},
                {id: 'not-ends-with-primary', description: 'Does not end with', arity: 2, categories: ['string']},
                {id: 'ordered-before-primary', description: 'Ordered before', arity: 2, categories: ['string']},
                {id: 'not-ordered-before-primary', description: 'Not ordered before', arity: 2, categories: ['string']},
                {id: 'ordered-after-primary', description: 'Ordered after', arity: 2, categories: ['string']},
                {id: 'not-ordered-after-primary', description: 'Not ordered after', arity: 2, categories: ['string']},
                {id: 'same-date-time', description: 'Same date and time', arity: 2, categories: ['date_time']},
                {id: 'not-same-date-time', description: 'Not the same date and time', arity: 2, categories: ['date_time']},
                {id: 'earlier-date-time', description: 'Earlier date and time', arity: 2, categories: ['date_time']},
                {id: 'later-date-time', description: 'Later date and time', arity: 2, categories: ['date_time']},
                {id: 'same-or-earlier-date-time', description: 'Same or earlier date and time', arity: 2, categories: ['date_time']},
                {id: 'same-or-later-date-time', description: 'Same or later date and time', arity: 2, categories: ['date_time']},
                {id: 'same-date', description: 'Same date', arity: 2, categories: ['date_time', 'date']},
                {id: 'not-same-date', description: 'Not the same date', arity: 2, categories: ['date_time', 'date']},
                {id: 'earlier-date', description: 'Earlier date', arity: 2, categories: ['date_time', 'date']},
                {id: 'later-date', description: 'Later date', arity: 2, categories: ['date_time', 'date']},
                {id: 'same-or-earlier-date', description: 'Same or earlier date', arity: 2, categories: ['date_time', 'date']},
                {id: 'same-or-later-date', description: 'Same or later date', arity: 2, categories: ['date_time', 'date']},
                {id: 'same-time', description: 'Same time', arity: 2, categories: ['date_time', 'time']},
                {id: 'not-same-time', description: 'Not the same time', arity: 2, categories: ['date_time', 'time']},
                {id: 'earlier-time', description: 'Earlier time', arity: 2, categories: ['date_time', 'time']},
                {id: 'later-time', description: 'Later time', arity: 2, categories: ['date_time', 'time']},
                {id: 'same-or-earlier-time', description: 'Same or earlier time', arity: 2, categories: ['date_time', 'time']},
                {id: 'same-or-later-time', description: 'Same or later time', arity: 2, categories: ['date_time', 'time']}

            ]
            
    });
});
