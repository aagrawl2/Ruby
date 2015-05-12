require 'rubygems'
require 'rest_client'
require 'json'
require 'pp'

def generate_access_token(client_id,client_secret,refresh_token,token_refresh_url)


	request_body_map = {
			:client_id => client_id,
			:client_secret => client_secret,
			:refresh_token => refresh_token,
			:grant_type => 'refresh_token'
		}
	token_refresh_url = 'https://accounts.google.com/o/oauth2/token'


	request = RestClient.post token_refresh_url, request_body_map, {:content_type => 'application/x-www-form-urlencoded'}

	#POST REQUEST
	response = request
	puts response.body
end

client_id         = '' 
client_secret     = ''
refresh_token     = ''
token_refresh_url = 'https://accounts.google.com/o/oauth2/token'

generate_access_token(client_id,client_secret,refresh_token,token_refresh_url)

