require 'rubygems'
require 'rest_client'
require 'json'
require 'pp'



def generate_refresh_token(client_id,client_secret,redirect_uri,authorization_code)


	request_body_map = {
			:client_id => client_id,
			:client_secret => client_secret,
			:redirect_uri => redirect_uri,
			:code => authorization_code,
			:grant_type => 'authorization_code'
		}
	token_refresh_url = 'https://accounts.google.com/o/oauth2/token'
	#Create a new request
	request = RestClient.post token_refresh_url, request_body_map, {:content_type => 'application/x-www-form-urlencoded'}

	#POST REQUEST
	response = request
	puts response.body
end

client_id          = '' 
client_secret      = ''
redirect_uri       = 'urn:ietf:wg:oauth:2.0:oob'
authorization_code = ''

generate_refresh_token(client_id,client_secret,redirect_uri,authorization_code)


